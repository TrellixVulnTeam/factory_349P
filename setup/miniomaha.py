#!/usr/bin/python

# Copyright 2009-2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A CherryPy-based webserver to host factory installation."""

# This a special fork from devserver for serving factory and may be executed in
# a very limited environment without full CrOS source tree.

import glob
import optparse
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib
import zipfile

import cherrypy

import miniomaha_engine

CACHED_ENTRIES = 12


def _LogUpdateMessage(message):
  cherrypy.log(message, 'UPDATE')


def _GetConfig(opts):
  """Returns the configuration for the miniomaha."""
  base_config = { 'global':
                  { 'server.log_request_headers': True,
                    'server.protocol_version': 'HTTP/1.1',
                    'server.socket_host':
                      '::' if socket.has_ipv6 else '0.0.0.0',
                    'server.socket_port': int(opts.port),
                    'server.socket_timeout': 6000,
                    'response.timeout': 6000,
                    'tools.staticdir.root':
                      os.path.dirname(os.path.abspath(sys.argv[0])),
                  },
                  '/api':
                  {
                    # Gets rid of cherrypy parsing post file for args.
                    'request.process_request_body': False,
                  },
                  '/update':
                  {
                    # Gets rid of cherrypy parsing post file for args.
                    'request.process_request_body': False,
                    'response.timeout': 10000,
                  },
                  # Sets up the static dir for file hosting.
                  '/static':
                  { 'tools.staticdir.dir': 'static',
                    'tools.staticdir.on': True,
                    'response.timeout': 10000,
                  },
                }

  return base_config

class BoardNotFoundException(Exception):
  pass

class OmahaPreparer(object):
  """Class for preparing all the necessary files for mini-omaha server."""
  conf_filename = 'miniomaha.conf'

  def __init__(self, script_dir, cache_dir, config_path=None):
    self.script_dir = script_dir
    self.cache_dir = cache_dir
    self.boards_to_update = None
    self.version_offset = None
    self.omaha_config_path = config_path

  def set_boards_to_update(self, _boards_to_update):
    self.boards_to_update = _boards_to_update

  def set_version_offset(self, _version_offset):
    self.version_offset = _version_offset

  def _read_config(self, config_path):
    output = {}
    with open(config_path, 'r') as f:
      exec(f.read(), output)
    return output['config']

  def generate_files_from_image(self, board_name):
    """Generate all the files and config with respect to a new image."""
    # create data directory if necessary
    data_dir = os.path.join(self.cache_dir, board_name)
    if os.path.exists(data_dir):
      shutil.rmtree(data_dir)
    os.makedirs(data_dir)

    # unzip the image of the target board
    for cached_file in os.listdir(self.cache_dir):
      if '%s_' % board_name in cached_file:
        zip_file = zipfile.ZipFile(os.path.join(self.cache_dir, cached_file))
        zip_file.extractall(data_dir)
        zip_file.close()

    # find the unzipped image
    file_path = glob.glob(os.path.join(data_dir, '*.bin'))[0]

    # call make_factory_package.sh, the result is stored in data_dir
    return_value = subprocess.call(
        [os.path.join(self.script_dir, 'make_factory_package.sh'),
         '--board=%s' % board_name,
         '--release=%s' % file_path,
         '--test=none',
         '--toolkit=none',
         '--hwid=none',
         '--omaha_data_dir=%s' % data_dir])
    if return_value:
      sys.exit("Failed to run make_factory_package.sh")
    os.remove(file_path)

    # read and delete the temporary config file
    config_path = os.path.join(data_dir, self.conf_filename)
    config = self._read_config(config_path)
    os.remove(config_path)

    # modify fields into the miniomaha readable form
    new_config = {}
    if config:
      new_config = config[0]
      for keys in new_config:
        if keys.endswith('_image'):
          dir_name = board_name
          if self.version_offset:
            dir_name = os.path.join(self.version_offset, board_name)
          new_config[keys] = os.path.join(dir_name, new_config[keys])

    return new_config

  def generate_miniomaha_files(self):
    """Generate files for the updated boards."""
    config_path = os.path.join(self.cache_dir, self.conf_filename)
    if os.path.exists(config_path):
      factory_configs = self._read_config(config_path)
    else:
      factory_configs = []

    # remove the old information of updated boards from config
    for board in self.boards_to_update:
      factory_configs[:] = [config for config in factory_configs
          if board not in config['qual_ids']]

    # generate the new configs and file for updated boards
    for board in self.boards_to_update:
      config = self.generate_files_from_image(board)
      if not config:
        sys.exit("Failed to generate config files")
      factory_configs.append(config)

    with open(config_path, 'w') as f:
      f.write('config=%s\n' % factory_configs)

  def setup_miniomaha_files(self):
    """Move the updated files to mini-omaha static directory."""
    omaha_dir = os.path.join(self.script_dir, 'static')
    if self.version_offset:
      omaha_dir = os.path.join(omaha_dir, self.version_offset)
    if not os.path.isdir(omaha_dir):
      os.makedirs(omaha_dir)
    for board in self.boards_to_update:
      target_dir = os.path.join(omaha_dir, board)
      if os.path.isdir(target_dir):
        shutil.rmtree(target_dir)
      os.rename(os.path.join(self.cache_dir, board), target_dir)
    omaha_config_path = (self.omaha_config_path or
                         os.path.join(omaha_dir, self.conf_filename))
    shutil.copy(os.path.join(self.cache_dir, self.conf_filename),
                omaha_config_path)


class ImageUpdater(object):
  """Class for requesting the latest stable image from server."""
  conf_url = 'https://dl.google.com/dl/edgedl/chromeos/recovery/recovery.conf'

  def __init__(self):
    self.board_images = []

  def _get_version_info(self):
    """Download and analyze the version information from server."""
    urllib.urlretrieve(self.conf_url, 'recovery.conf')

    with open('recovery.conf', 'r') as f:
      current_version = '0.0.0.0'
      for line in f:
        stanza = line.strip().split('=')
        if stanza[0] == 'url':
          if (current_version, stanza[1]) not in self.board_images:
            self.board_images.append((current_version, stanza[1]))
        elif stanza[0] == 'version':
          current_version = stanza[1]

  def update_image(self, board_name, cache_dir):
    """Check and update an image of the give board name."""
    self._get_version_info()
    update_filename = ''
    update_url = ''
    for version, url in self.board_images:
      if '%s_' % board_name in url:
        update_filename = '%s_%s.bin.zip' % (board_name, version)
        update_url = url
        break

    if not update_filename:
      raise BoardNotFoundException

    need_update = True
    for cached_file in os.listdir(cache_dir):
      if '%s_' % board_name in cached_file:
        if cached_file == update_filename:
          need_update = False
        else:
          os.remove(os.path.join(cache_dir, cached_file))
        break

    if need_update:
      urllib.urlretrieve(update_url, os.path.join(cache_dir, update_filename))

    return need_update

class UpdateChecker(object):
  """Class for doing peridically update check."""

  def __init__(self, opts, script_dir, cache_dir, _updater, lock):
    self.opts = opts
    self.script_dir = script_dir
    self.cache_dir = cache_dir
    self.updater = _updater
    self.update_lock = lock
    self.timer = None
    self.base_dir = os.path.realpath(self.opts.data_dir)
    self.next_version = 1
    if opts.boards:
      self._UpdateCheck(opts.boards.split(','))
    else:
      self._UpdateCheck()

  def _CleanUpConfig(self):
    """Put the updated files into initial position"""
    if self.updater.GetActiveConfigIndex() == 1:
      # No update
      return
    initial_config = self.updater.GetConfig(0)
    last_config = self.updater.GetConfig(self.updater.GetActiveConfigIndex())
    # Parse initial dir for initial_dir/board/release_image
    initial_dir = os.path.dirname(initial_config[0]['release_image'])
    initial_dir = os.path.dirname(initial_dir)
    initial_dir = os.path.join(self.base_dir, initial_dir)

    # Move the final version of each board into initial dir
    for board_conf in last_config:
      board_dir = os.path.dirname(board_conf['release_image'])
      board_dir = os.path.join(self.base_dir, board_dir)
      board_name = os.path.basename(board_dir)
      target_dir = os.path.join(initial_dir, board_name)

      if os.path.samefile(board_dir, target_dir):
        continue
      if os.path.isdir(target_dir):
        shutil.rmtree(target_dir)
      shutil.move(board_dir, target_dir)

      # Correct the file path and pop unnecessary keys
      for key in board_conf.copy().iterkeys():
        if key.endswith('_image'):
          board_conf[key] = os.path.join(target_dir,
                                         os.path.basename(board_conf[key]))
        elif key.endswith('_size'):
          board_conf.pop(key)

    # Overwrite the config file
    with open(self.opts.factory_config, 'w') as file_handle:
      file_handle.write('config=%s\n' % last_config)

    # Remove _ver*/
    for version in glob.glob(os.path.join(self.base_dir, '_ver*')):
      shutil.rmtree(version)

  def _UpdateCheck(self, boards=None):
    """Do update check periodically."""
    # Initialize preparer and updater
    if not os.path.exists(self.cache_dir):
      os.makedirs(self.cache_dir)
    image_updater = ImageUpdater()
    image_preparer = OmahaPreparer(self.script_dir, self.cache_dir)

    # If boards is set, do an initial update setup for those boards
    if boards:
      init_preparer = OmahaPreparer(
          self.script_dir, self.cache_dir,
          self.opts.factory_config)
      for board in list(boards):
        try:
          updated = image_updater.update_image(board, self.cache_dir)
        except BoardNotFoundException:
          _LogUpdateMessage('WARNING: No board named %s is found, ignored' %
                            board)
          boards.remove(board)
      init_preparer.set_boards_to_update(boards)
      init_preparer.generate_miniomaha_files()
      init_preparer.setup_miniomaha_files()
      self.updater.ImportFactoryConfigFile(self.opts.factory_config, False)

    # Try to update all boards in config
    updated_boards = []
    active_config = self.updater.GetConfig(self.updater.GetActiveConfigIndex())
    for board_conf in active_config:
      # The format in config is qual_id: set(['board'])
      for board in board_conf['qual_ids']:
        updated = image_updater.update_image(board, self.cache_dir)
        if updated:
          updated_boards.append(board)
          _LogUpdateMessage('Detect update for board %s' % board)

    if not updated_boards:
      _LogUpdateMessage('Everything up-to-date, update check finished')
    else:
      _LogUpdateMessage('Start updating')
      version_offset = '_ver%s' % self.next_version
      self.next_version += 1

      # Prepare the files for the newly downloaded boards
      image_preparer.set_boards_to_update(updated_boards)
      image_preparer.set_version_offset(version_offset)
      image_preparer.generate_miniomaha_files()
      image_preparer.setup_miniomaha_files()

      data_dir = self.base_dir
      # Change config, critical session
      with self.update_lock:
        # Read config
        config_dir = os.path.join(data_dir, version_offset)
        config_path = os.path.join(config_dir, 'miniomaha.conf')
        self.updater.ImportFactoryConfigFile(config_path, False)

    # Restart timers
    # Time interval between each update check, by seconds
    self.timer = threading.Timer(self.opts.interval, self._UpdateCheck)
    self.timer.daemon = True
    self.timer.start()

  def cleanup(self):
    self.timer.cancel()
    self._CleanUpConfig()

class ApiRoot(object):
  """RESTful API for Dev Server information."""
  exposed = True

  @cherrypy.expose
  def hostinfo(self, ip):
    """Returns a JSON dictionary containing information about the given ip.

    Not all information may be known at the time the request is made. The
    possible keys are:

        last_event_type: int
            Last update event type received.

        last_event_status: int
            Last update event status received.

        last_known_version: string
            Last known version recieved for update ping.

        forced_update_label: string
            Update label to force next update ping to use. Set by setnextupdate.

    See the OmahaEvent class in update_engine/omaha_request_action.h for status
    code definitions. If the ip does not exist an empty string is returned."""
    return updater.HandleHostInfoPing(ip)

  @cherrypy.expose
  def setnextupdate(self, ip):
    """Allows the response to the next update ping from a host to be set.

    Takes the IP of the host and an update label as normally provided to the
    /update command."""
    body_length = int(cherrypy.request.headers['Content-Length'])
    label = cherrypy.request.rfile.read(body_length)

    if label:
      label = label.strip()
      if label:
        return updater.HandleSetUpdatePing(ip, label)
    raise cherrypy.HTTPError(400, 'No label provided.')


class DevServerRoot(object):
  """The Root Class for the Dev Server.

  CherryPy works as follows:
    For each method in this class, cherrpy interprets root/path
    as a call to an instance of DevServerRoot->method_name.  For example,
    a call to http://myhost/build will call build.  CherryPy automatically
    parses http args and places them as keyword arguments in each method.
    For paths http://myhost/update/dir1/dir2, you can use *args so that
    cherrypy uses the update method and puts the extra paths in args.
  """
  api = ApiRoot()
  fail_msg = 'Previous session from %s, uuid: %s, start at %s did not complete'
  time_string = '%d/%b/%Y %H:%M:%S'

  def __init__(self, lock, auto_update):
    self.client_table = {}
    self.update_lock = lock
    self.auto_update = auto_update

  def GetClientConfigIndex(self, ip):
    return self.client_table[ip]['config_index']

  def SetClientConfigIndex(self, ip, index):
    self.client_table[ip]['config_index'] = index

  def GetClientStartTime(self, ip):
    return self.client_table[ip]['start_time']

  def SetClientStartTime(self, ip, start_time):
    self.client_table[ip]['start_time'] = start_time

  @cherrypy.expose
  def index(self):
    return 'Welcome to the Dev Server!'

  @cherrypy.expose
  def update(self):
    client_ip = cherrypy.request.remote.ip.split(':')[-1]
    body_length = int(cherrypy.request.headers['Content-Length'])
    data = cherrypy.request.rfile.read(body_length)

    # For backward compatibility of old install shim.
    # Updater should work anyway.
    if client_ip not in self.client_table:
      if self.auto_update:
        _LogUpdateMessage(
            'WARNING: Detect unrecorded ip: %s. '
            'If you are using an old factory install shim, '
            'there may be unexpected outcome in --auto_update mode' %
            client_ip)
      return updater.HandleUpdatePing(data, updater.GetActiveConfigIndex())

    return updater.HandleUpdatePing(data,
                                    self.GetClientConfigIndex(client_ip))

  @cherrypy.expose
  def greetings(self, label, uuid):
    # Temporarily use ip as identifier.
    # This may be changed if we found better session ids
    client_ip = cherrypy.request.remote.ip.split(':')[-1]

    if label != 'hello' and client_ip not in self.client_table:
      _LogUpdateMessage('Unexpected %s notification from %s, uuid: %s' %
                        (label, client_ip, uuid))
      return 'Wrong notification'

    if label == 'hello':
      if client_ip in self.client_table:
        # previous session did not complete, print error to log
        start_time = time.strftime(
            self.time_string,
            time.localtime(self.GetClientStartTime(client_ip)))
        _LogUpdateMessage(self.fail_msg % (client_ip, uuid, start_time))

      self.client_table[client_ip] = {}
      self.SetClientStartTime(client_ip, time.time())
      _LogUpdateMessage('Start a install session for %s, uuid: %s' %
                        (client_ip, uuid))

      with self.update_lock:
        self.SetClientConfigIndex(client_ip, updater.GetActiveConfigIndex())

      return 'hello'

    elif label == 'download_complete':
      _LogUpdateMessage(
          'Session from %s, uuid: %s, '
          'successfully downloaded all necessary files' %
          (client_ip, uuid))
      return 'download complete'

    elif label == 'goodbye':
      elapse_time = time.time() - self.GetClientStartTime(client_ip)
      _LogUpdateMessage(
          'Session from %s, uuid: %s, '
          'has been completed, elapse time is %s seconds' %
          (client_ip, uuid, elapse_time))
      self.client_table.pop(client_ip)
      return 'goodbye'

  #TODO(chunyen): move this to cherrypy exit callback
  def __del__(self):
    # Write log for those incomplete session
    for client_ip in self.client_table:
      start_time = time.strftime(
          self.time_string,
          time.localtime(self.GetClientStartTime(client_ip)))
      _LogUpdateMessage(self.fail_msg % (client_ip, start_time))


if __name__ == '__main__':
  base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
  usage = 'usage: %prog [options]'
  parser = optparse.OptionParser(usage)
  parser.add_option('--data_dir', dest='data_dir',
                    help='Writable directory where static lives',
                    default=os.path.join(base_path, 'static'))
  parser.add_option('--factory_config', dest='factory_config',
                    help='Config file for serving images from factory floor.',
                    default=None)
  parser.add_option('--port', default=8080,
                    help='Port for the dev server to use.')
  parser.add_option('--proxy_port', default=None,
                    help='Port to have the client connect to (testing support)')
  parser.add_option('--validate_factory_config', action="store_true",
                    dest='validate_factory_config',
                    help='Validate factory config file, then exit.')
  parser.add_option('--log', dest='log_path',
                    help='Path for server execution log',
                    default=os.path.join(base_path, 'miniomaha.log'))
  parser.add_option('--auto_update', action='store_true', dest='auto_update',
                    help='Enable auto updating image from server')
  parser.add_option('--cache', dest='cache_dir', default=None,
                    help='Cache_dir for auto update images')
  parser.add_option('--interval', dest='interval', default=1800, type=int,
                    help='Interval between each update check')
  parser.add_option('--boards', dest='boards', default=None,
                    help='Name of boards to track in auto-update mode, '
                         'split by comma.')
  parser.set_usage(parser.format_help())
  (options, _) = parser.parse_args()

  static_dir = os.path.realpath(options.data_dir)
  os.system('mkdir -p %s' % static_dir)

  cherrypy.log('Data dir is %s' % options.data_dir, 'DEVSERVER')
  cherrypy.log('Serving from %s' % static_dir, 'DEVSERVER')

  updater = miniomaha_engine.ServerEngine(
      static_dir=static_dir,
      proxy_port=options.proxy_port
  )
  updater_lock = threading.Lock()

  # Auto update is not support in validate factory config mode
  if options.validate_factory_config and options.auto_update:
    cherrypy.log('Auto update is not support when validating factory config',
                 'DEVSERVER')
    options.auto_update = False

  # --boards only works in auto update mode
  if options.boards and not options.auto_update:
    cherrypy.log('--boards only works in auto_update mode')
    options.boards = None

  # Sanity-check for use of validate_factory_config.
  # In previous version, the default configuration file is in base_path,
  # but now it is in data_dir,
  # so we want to check both for backward compatibility.
  if not options.factory_config:
    config_files = (os.path.join(base_path, 'miniomaha.conf'),
                    os.path.join(options.data_dir, 'miniomaha.conf'))
    exists = map(os.path.exists, config_files)

    # When boards is set, we always use the current default data dir
    if options.boards:
      options.factory_config = config_files[1]
    elif all(exists):
      parser.error('Confusing factory config files.\n'
                   'Please remove the old config file in %s' % base_path)
    elif any(exists):
      options.factory_config = config_files[exists.index(True)]
    else:
      parser.error('No factory files found')

  # When boards is set, we should import config after the first update check.
  if not options.boards:
    updater.ImportFactoryConfigFile(options.factory_config,
                                    options.validate_factory_config)

  # We've done validating factory config, exit now!
  if options.validate_factory_config:
    sys.exit(0)

  if options.auto_update:
    # Set up cache directory.
    options.cache_dir = (options.cache_dir or
                         os.path.join(base_path, 'cache_dir'))
    # Ensure that the configure file in cache directory is the same as that
    # in data directory.
    if os.path.exists(options.factory_config):
      shutil.copy(options.factory_config, options.cache_dir)
    update_checker = UpdateChecker(options, base_path, options.cache_dir,
                                   updater, updater_lock)

  # Since cheerypy need an existing file to append log,
  # here we make sure the log file path exist and ready for writing.
  with open(options.log_path, 'a'):
    pass
  cherrypy.log.screen = True
  cherrypy.log.access_file = options.log_path
  cherrypy.log.error_file = options.log_path
  cherrypy.quickstart(DevServerRoot(updater_lock, options.auto_update),
                      config=_GetConfig(options))
  if options.auto_update:
    update_checker.cleanup()
    # Sync the config file again to avoid error if user run
    # get_recovery_image.py
    shutil.copy(options.factory_config, options.cache_dir)
