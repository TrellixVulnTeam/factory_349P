#!/usr/bin/python2
#
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""BigQuery upload output plugin.

Limits to keep in mind:
  daily load job limit per table: 1000 (every 86.4 seconds)
  daily load job limit per project: 10,000
  JSON row size: 2 MB
  JSON max file size: 5 TB
  max size per load job: 12 TB
"""

from __future__ import print_function

import os
import shutil
import time

# pylint: disable=import-error
from google.cloud import bigquery
from google.oauth2 import service_account

import instalog_common  # pylint: disable=W0611
from instalog import plugin_base
from instalog.utils.arg_utils import Arg
from instalog.utils import file_utils


_BIGQUERY_SCOPE = 'https://www.googleapis.com/auth/bigquery'
_BIGQUERY_REQUEST_MAX_FAILURES = 20
_JOB_NAME_PREFIX = 'instalog_'
_JSON_MIMETYPE = 'NEWLINE_DELIMITED_JSON'
_DEFAULT_INTERVAL = 90
_DEFAULT_BATCH_SIZE = 10000


class OutputBigQuery(plugin_base.OutputPlugin):

  ARGS = [
      Arg('interval', (int, float),
          'Frequency to upload a BigQuery import, in seconds.  Since BigQuery '
          'only allows 1000 imports per day per table, a value above 86.4 '
          'seconds is recommended to guarantee this limit will not be reached.',
          optional=True, default=_DEFAULT_INTERVAL),
      Arg('batch_size', int,
          'How many events to queue before transmitting.',
          optional=True, default=_DEFAULT_BATCH_SIZE),
      Arg('key_path', (str, unicode),
          'Path to BigQuery service account JSON key file.',
          optional=False),
      Arg('project_id', (str, unicode), 'Google Cloud project ID.',
          optional=False),
      Arg('dataset_id', (str, unicode), 'BigQuery dataset ID.',
          optional=False),
      Arg('table_id', (str, unicode), 'BigQuery target table name.',
          optional=False)
  ]

  def __init__(self, *args, **kwargs):
    self.client = None
    self.table = None
    super(OutputBigQuery, self).__init__(*args, **kwargs)

  def SetUp(self):
    """Builds the client object and the table object to run BigQuery calls."""
    self.client = self.BuildClient()
    self.table = self.BuildTable()

  def Main(self):
    """Main thread of the plugin."""
    while not self.IsStopping():
      if not self.PrepareAndUpload():
        # TODO(kitching): Find a better way to block the plugin when we are in
        #                 one of the PAUSING, PAUSED, or UNPAUSING states.
        self.Sleep(1)

  def BuildClient(self):
    """Builds a BigQuery client object."""
    credentials = service_account.Credentials.from_service_account_file(
        self.args.key_path, scopes=(_BIGQUERY_SCOPE,))
    return bigquery.Client(project=self.args.project_id,
                           credentials=credentials)

  def BuildTable(self):
    """Builds a BigQuery table object."""
    dataset = bigquery.Dataset(self.args.dataset_id, self.client)
    table = bigquery.Table(self.args.table_id, dataset, self.GetTableSchema())
    if table.exists():
      table.reload()
    else:
      table.create()
    return table

  def GetTableSchema(self):
    """Returns a list of fields in the table schema.

    Fields may be nested according to BigQuery RECORD type specification.

    Example:
        [
            {'name': 'event_time', 'type': 'TIMESTAMP'},
            {'name': 'event_fields', 'type': RECORD', 'fields':
                [
                    {'name': 'key': 'type': 'STRING'},
                    {'name': 'value': 'type': 'STRING'}
                ]
            }
        ]
    """
    raise NotImplementedError

  def ConvertEventToRow(self, event):
    """Converts an event to its corresponding BigQuery table row JSON string.

    Returns:
      A JSON string corresponding to the table row.  None if the event should
      not create any table row.

    Raises:
      Exception if something went wrong (unexpected data in the Event).  The
      exception will be logged and the row will be ignored.
    """
    raise NotImplementedError

  def PrepareFile(self, event_stream, json_path):
    """Retrieves events from event_stream and dumps them to the json_path.

    Returns:
      A tuple of (event_count, row_count), where:
        event_count: The number of events from event_stream.
        row_count: The number of BigQuery format events from event_stream.
    """
    event_count = 0
    row_count = 0
    with open(json_path, 'w') as f:
      for event in event_stream.iter(timeout=self.args.interval,
                                     count=self.args.batch_size):
        json_row = None
        try:
          json_row = self.ConvertEventToRow(event)
        except Exception:
          self.warning('Error converting event to row: %s',
                       event, exc_info=True)
        if json_row is not None:
          f.write(json_row + '\n')
          row_count += 1
        event_count += 1

    return event_count, row_count

  def PrepareAndUpload(self):
    """Retrieves events, converts them to BigQuery format, and uploads them."""
    event_stream = self.NewStream()
    if not event_stream:
      return False

    with file_utils.UnopenedTemporaryFile(
        prefix='output_bigquery_') as json_path:
      event_count, row_count = self.PrepareFile(event_stream, json_path)

      if self.IsStopping():
        self.info('Plugin is stopping! Abort %d events', event_count)
        event_stream.Abort()
        return False

      # No processed events result in BigQuery table rows.
      if row_count == 0:
        self.info('Commit %d events (%d rows)', event_count, row_count)
        event_stream.Commit()
        return False

      self.info('Uploading %d rows into BigQuery...', row_count)
      try:
        with open(json_path, 'rb') as f:
          job_id = '%s%d' % (_JOB_NAME_PREFIX, time.time())
          # No need to run job.begin() since upload_from_file() takes care of
          # this.
          job = self.table.upload_from_file(
              file_obj=f,
              source_format=_JSON_MIMETYPE,
              num_retries=_BIGQUERY_REQUEST_MAX_FAILURES,
              job_name=job_id,
              size=os.path.getsize(json_path))

        # Wait for job to complete.
        job.result()

      except Exception:
        event_stream.Abort()
        self.exception('Insert failed')
        self.info('Abort %d events (%d rows)', event_count, row_count)
        return False
      else:
        if job.state == 'DONE':
          if job.output_rows != row_count:
            shutil.copyfile(json_path, json_path + '.backup')
            self.error('Row count is not equal to output rows! This should not'
                       'happen! Copy the json file to %s.backup!', json_path)

          self.info('Commit %d events (%d rows)', event_count, row_count)
          event_stream.Commit()
          return True
        else:
          event_stream.Abort()
          self.warning('Insert failed with errors: %s', job.errors)
          self.info('Abort %d events (%d rows)', event_count, row_count)
          return False


if __name__ == '__main__':
  plugin_base.main()
