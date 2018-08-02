#!/usr/bin/env python
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import BaseHTTPServer
import logging
import os
import SimpleHTTPServer

# TODO(youcheng): Bundle non-standard libraries.
from jsonrpclib import SimpleJSONRPCServer

import factory_common  # pylint: disable=unused-import
from cros.factory.test_list_editor.backend import rpc
from cros.factory.utils import sys_utils


PORT = 4013

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
STATIC_DIR = os.path.realpath(
    os.path.join(SCRIPT_DIR, '..', 'frontend', 'dist'))
PUBLIC_TEST_LISTS_DIR = os.path.realpath(
    os.path.join(SCRIPT_DIR, '..', '..', 'test', 'test_lists'))
PRIVATE_TEST_LISTS_RELPATH = os.path.join(
    'chromeos-base', 'factory-board', 'files', 'py', 'test', 'test_lists')


class Server(object):

  class HTTPRequestHandler(
      SimpleJSONRPCServer.SimpleJSONRPCRequestHandler,
      SimpleHTTPServer.SimpleHTTPRequestHandler):

    def end_headers(self):
      if self.command == 'POST':
        # Allow CORS for front-end development.
        self.send_header('Access-Control-Allow-Origin', '*')
      BaseHTTPServer.BaseHTTPRequestHandler.end_headers(self)

  def __init__(self, port, dirs):
    self.port = port
    self.dirs = dirs
    self.httpd = SimpleJSONRPCServer.SimpleJSONRPCServer(
        ('', port), Server.HTTPRequestHandler)
    self.httpd.register_introspection_functions()
    self.httpd.register_instance(rpc.RPC(self))

  def start(self):
    logging.info('httpd started at http://localhost:%d/', self.port)
    self.httpd.serve_forever()


def main():

  def locate(path, name):
    while True:
      if os.path.isdir(os.path.join(path, name)):
        return path
      if path == '/':
        return None
      path = os.path.dirname(path)

  parser = argparse.ArgumentParser()
  parser.add_argument(
      '-b', '--board', help='Board name of the private overlay to open.')
  parser.add_argument(
      '-p', '--port', default=PORT, type=int,
      help='The port to listen for HTTP requests.')
  args = parser.parse_args()

  dirs = [('factory', PUBLIC_TEST_LISTS_DIR)]
  if args.board:
    if sys_utils.InCrOSDevice():
      raise ValueError('BOARD may not be set in DUT environment.')
    path = locate(SCRIPT_DIR, '.repo')
    if not path:
      raise RuntimeError('Not in a Chromium OS source tree.')
    path = os.path.join(
        path, 'src', 'private-overlays', 'overlay-%s-private' % args.board)
    if not os.path.isdir(path):
      raise RuntimeError('Private overlay %r not found.' % path)
    path = os.path.join(path, PRIVATE_TEST_LISTS_RELPATH)
    if not os.path.isdir(path):
      raise RuntimeError('Directory %r not found.' % path)
    dirs.append((args.board, path))
  else:
    path = locate(os.getcwd(), '.git')
    if path:
      path = os.path.join(path, PRIVATE_TEST_LISTS_RELPATH)
      if os.path.isdir(path):
        dirs.append((os.path.dirname(path).split('-')[1], path))

  if not os.path.isdir(STATIC_DIR):
    # TODO(youcheng): Pull static files automatically.
    raise RuntimeError('%r is required.' % STATIC_DIR)
  os.chdir(STATIC_DIR)

  server = Server(args.port, dirs)
  server.start()
  # TODO(youcheng): Launch browser automatically.


if __name__ == '__main__':
  logging.getLogger().setLevel(logging.INFO)
  main()
