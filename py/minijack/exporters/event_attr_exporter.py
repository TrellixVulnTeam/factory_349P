# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

import factory_common  # pylint: disable=W0611
from cros.factory.minijack import db
from cros.factory.minijack.datatypes import EventPacket
from cros.factory.minijack.exporters.base import ExporterBase
from cros.factory.minijack.models import Event, Attr


class EventAttrExporter(ExporterBase):
  """The exporter to create the Event and Attr tables.

  TODO(waihong): Unit tests.
  """
  def __init__(self, database):
    super(EventAttrExporter, self).__init__(database)
    self._event_table = None
    self._attr_table = None

  def Setup(self):
    super(EventAttrExporter, self).Setup()
    self._event_table = self._database.GetOrCreateTable(Event)
    self._attr_table = self._database.GetOrCreateTable(Attr)

  def Handle_all(self, packet):
    """A handler for all event types."""
    # Just insert the row for speed-up. May raises an exception if the row
    # already exists.
    try:
      # Insert to Event first. If it finds duplication, skips Attr insertion.
      self._InsertEvent(packet)
      self._InsertAttr(packet)
    except db.IntegrityError:
      logging.warn('The Event/Attr (%s, %s) already exists in the table',
                   packet.preamble.get('device_id'), packet.event.get('TIME'))

  def _InsertEvent(self, packet):
    """Retrieves event information and inserts to Event table"""
    row = Event(
      device_id      = packet.preamble.get('device_id'),
      time           = packet.event.get('TIME'),
      preamble_time  = packet.preamble.get('TIME'),
      event          = packet.event.get('EVENT'),
      event_seq      = int(packet.event.get('SEQ')),
      preamble_seq   = int(packet.preamble.get('SEQ')),
      boot_id        = packet.preamble.get('boot_id'),
      boot_sequence  = int(packet.preamble.get('boot_sequence')),
      factory_md5sum = packet.preamble.get('factory_md5sum'),
      filename       = packet.preamble.get('filename'),
      image_id       = packet.preamble.get('image_id'),
      log_id         = packet.preamble.get('log_id'),
    )
    self._event_table.InsertRow(row)

  def _InsertAttr(self, packet):
    """Retrieves attr information and inserts to Attr table"""
    RESERVED_PATH = ('EVENT', 'SEQ', 'TIME')
    rows = []
    # As the event is a tree struct which contains dicts or lists,
    # we flatten it first. The hierarchy is recorded in the Attr column.
    for attr, value in EventPacket.FlattenAttr(packet.event):
      if attr not in RESERVED_PATH:
        row = Attr(
          device_id = packet.preamble.get('device_id'),
          time      = packet.event.get('TIME'),
          attr      = _ToAsciiString(attr),
          value     = _ToAsciiString(value),
        )
        rows.append(row)
    if rows:
      self._attr_table.InsertRows(rows)


def _ToAsciiString(value):
  """Convert any type object to an ascii string."""
  if isinstance(value, str):
    return value.encode('string_escape')
  elif isinstance(value, unicode):
    return value.encode('unicode_escape')
  else:
    return str(value)
