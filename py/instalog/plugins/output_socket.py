#!/usr/bin/python2
#
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Output socket plugin.

Transmits events to an input socket plugin running on another Instalog node.

See socket_common.py for protocol definition.
"""

from __future__ import print_function

import hashlib
import os
import socket
import time

import instalog_common  # pylint: disable=W0611
from instalog import plugin_base
from instalog.plugins import socket_common
from instalog.utils.arg_utils import Arg
from instalog.utils import time_utils


_DEFAULT_BATCH_SIZE = 5000
_DEFAULT_TIMEOUT = 5
_FAILED_CONNECTION_INTERVAL = 60


class OutputSocket(plugin_base.OutputPlugin):

  ARGS = [
      Arg('batch_size', int, 'How many events to queue before transmitting.',
          optional=True, default=_DEFAULT_BATCH_SIZE),
      Arg('timeout', (int, float), 'Timeout to transmit without full batch.',
          optional=True, default=_DEFAULT_TIMEOUT),
      Arg('hostname', (str, unicode), 'Hostname that server should bind to.',
          optional=False),
      Arg('port', int, 'Port that server should bind to.',
          optional=True, default=socket_common.DEFAULT_PORT)
  ]

  def __init__(self, *args, **kwargs):
    self._sock = None
    super(OutputSocket, self).__init__(*args, **kwargs)

  def Main(self):
    """Main thread of the plugin."""
    # Boolean flag to indicate whether or not the target is currently available.
    target_available = False
    last_unavailable_time = float('-inf')

    while not self.IsStopping():
      # Should we verify the connection first?
      if not target_available and not self.Ping():
        if (time_utils.MonotonicTime() >
            (last_unavailable_time + _FAILED_CONNECTION_INTERVAL)):
          last_unavailable_time = time_utils.MonotonicTime()
          self.info('Connection to target unavailable')
        self.Sleep(_FAILED_CONNECTION_INTERVAL)
        continue
      target_available = True

      # Since we need to know the number of events being sent before beginning
      # the transmission, cache events in memory before making the connection.
      events = []
      event_stream = self.NewStream()
      if not event_stream:
        # TODO(kitching): Find a better way to block the plugin when we are in
        #                 one of the PAUSING, PAUSED, or UNPAUSING states.
        self.Sleep(1)
        continue

      for event in event_stream.iter(timeout=self.args.timeout,
                                     count=self.args.batch_size):
        events.append(event)

      # If no events are available, don't bother sending an empty transmission.
      if not events:
        self.debug('No events available for transmission')
        event_stream.Commit()
        continue

      try:
        self.GetSocket()
        # Send the number of events followed by each one.
        start_time = time.time()
        self.SendInt(len(events))
        total_bytes = 0
        for event in events:
          total_bytes += self.SendEvent(event)

        # Confirmation of receipt.
        self.debug('Waiting for data-received (syn)...')
        if not self.CheckSuccess(socket_common.DATA_RECEIVED_CHAR):
          self.info('Failure waiting for data-received (syn); abort %d events',
                    len(events))
          raise Exception
        self.debug('Sending request-emit (ack)...')
        self._sock.sendall(socket_common.REQUEST_EMIT_CHAR)


        # Check for success or failure.  Commit or abort the stream.
        self.debug('Waiting for emit-success (syn-ack)...')
        if self.CheckSuccess(socket_common.EMIT_SUCCESS_CHAR):
          self.debug('Success; commit %d events', len(events))
          event_stream.Commit()
        else:
          self.info('Failure; abort %d events', len(events))
          raise Exception
        elapsed_time = time.time() - start_time

        # Size and speed information.
        total_kbytes = total_bytes / 1024.0
        self.info(
            'Transmitted %d events, total %.2f kB in %.1f sec (%.2f kB/sec)',
            len(events), total_kbytes, elapsed_time,
            total_kbytes / elapsed_time)

      except socket.error as e:
        event_stream.Abort()
        if e.errno == 111:  # Connection refused
          self.error('Could not make connection to target server')
        else:
          self.exception('Connection or transfer failed')
        target_available = False
        self.Sleep(1)
      except Exception:
        event_stream.Abort()
        self.exception('Connection or transfer failed')
        target_available = False
        self.Sleep(1)
      finally:
        # Shutdown and close the socket.
        try:
          self.debug('Closing socket')
          self._sock.shutdown(socket.SHUT_RDWR)
          self._sock.close()
        except Exception:
          self.exception('Error closing socket')

  def Ping(self):
    """Pings the input socket with an empty-length transmission."""
    try:
      self.GetSocket()
      self.SendInt(0)
      return self.CheckSuccess(socket_common.PING_RESPONSE)
    except socket.error:
      return False
    except Exception:
      self.exception('Unexpected ping failure')
      return False

  def GetSocket(self):
    """Creates and returns a new socket connection to the target host."""
    self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self._sock.settimeout(socket_common.SOCKET_TIMEOUT)
    self._sock.connect((self.args.hostname, self.args.port))

  def SendItem(self, item):
    """Transmits an item over the socket stream."""
    self._sock.sendall('%s%s' % (item, socket_common.SEPARATOR))

  def SendInt(self, num):
    """Transmits an integer over the socket stream."""
    self.SendItem(str(num))

  def SendField(self, data):
    """Transmits a field over the socket stream.

    Returns:
      Number of bytes sent.
    """
    local_hash = hashlib.sha1()
    local_hash.update(data)
    data_size = len(data)
    self.SendInt(data_size)
    self._sock.sendall(data)
    self.SendItem(local_hash.hexdigest())
    return data_size

  def SendEvent(self, event):
    """Transmits an Instalog Event over the socket stream.

    Returns:
      Number of bytes sent (serialized_event + attachments).
    """
    total_bytes = 0
    # Since we transfer attachments separately, we don't need to transfer their
    # names and paths within the event itself.
    attachments = event.attachments
    event.attachments = {}
    serialized_event = event.Serialize()
    total_bytes += self.SendField(serialized_event)
    self.SendInt(len(attachments))
    for att_id, att_path in attachments.iteritems():
      total_bytes += self.SendAttachment(att_id, att_path)
    return total_bytes

  def SendAttachment(self, att_id, att_path):
    """Transmits an Event's attachment over the socket stream.

    Returns:
      Number of bytes sent (att_id + att_data).
    """
    att_id_size = self.SendField(att_id)
    att_size = os.path.getsize(att_path)
    self.SendInt(att_size)

    local_hash = hashlib.sha1()
    with open(att_path) as f:
      while True:
        read_bytes = f.read(socket_common.CHUNK_SIZE)
        if not read_bytes:
          break
        local_hash.update(read_bytes)
        self._sock.sendall(read_bytes)
    self.SendItem(local_hash.hexdigest())
    return att_id_size + att_size

  def CheckSuccess(self, expected_char):
    """Checks that the transmission was committed on the remote side."""
    result = self._sock.recv(1)
    return result == expected_char


if __name__ == '__main__':
  plugin_base.main()
