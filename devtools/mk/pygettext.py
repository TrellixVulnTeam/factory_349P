#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Originally written by Barry Warsaw <barry@zope.com>
#
# Minimally patched to make it even more xgettext compatible
# by Peter Funk <pf@artcom-gmbh.de>
#
# 2002-11-22 Jürgen Hermann <jh@web.de>
# Added checks that _() only contains string literals, and
# command line args are resolved to module lists, i.e. you
# can now pass a filename, a module or package name, or a
# directory (including globbing chars, important for Win32).
# Made docstring fit in 80 chars wide displays using pydoc.

# This file was modified to support Python and HTML strings in Chrome OS
# factory software.
# The original version is from Python source repository:
# https://hg.python.org/cpython/file/2.7/Tools/i18n/pygettext.py


import argparse
import ast
import cgi
import HTMLParser
import os
import re
import sys
import time
import token
import tokenize


POT_HEADER = r"""# SOME DESCRIPTIVE TITLE.
# Copyright (C) YEAR ORGANIZATION
# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.
#
msgid ""
msgstr ""
"Project-Id-Version: PACKAGE VERSION\n"
"POT-Creation-Date: %(time)s\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: LANGUAGE <LL@li.org>\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=CHARSET\n"
"Content-Transfer-Encoding: ENCODING\n"

"""


escapes = []


def MakeEscapes():
  for i in range(256):
    if 32 <= i <= 126:
      escapes.append(chr(i))
    else:
      escapes.append("\\%03o" % i)
  escapes[ord('\\')] = r'\\'
  escapes[ord('\t')] = r'\t'
  escapes[ord('\r')] = r'\r'
  escapes[ord('\n')] = r'\n'
  escapes[ord('\"')] = r'\"'


def Escape(s):
  return ''.join(escapes[ord(c)] for c in s)


def Normalize(s):
  # This converts the various Python string types into a format that is
  # appropriate for .po files, namely much closer to C style.
  lines = s.splitlines(True)
  if len(lines) != 1:
    lines.insert(0, '')
  return '\n'.join('"%s"' % Escape(l) for l in lines)


def WritePot(fp, messages, width):
  timestamp = time.strftime('%Y-%m-%d %H:%M+%Z')
  print >> fp, POT_HEADER % {'time': timestamp}

  # Collect files with same text together.
  message_dict = {}
  for fileloc, text in messages:
    message_dict.setdefault(text, set()).add(fileloc)

  messages = []
  for text, files in message_dict.iteritems():
    files = list(files)
    files.sort()
    messages.append((files, text))
  messages.sort()

  for files, text in messages:
    locline = '#:'
    filenames = set(filename for filename, unused_lineno in files)
    for filename in sorted(list(filenames)):
      s = ' ' + filename
      if len(locline) + len(s) <= width:
        locline = locline + s
      else:
        print >> fp, locline
        locline = "#:" + s
    if len(locline) > 2:
      print >> fp, locline
    print >> fp, 'msgid', Normalize(text)
    print >> fp, 'msgstr ""\n'


class PyTokenEater(object):
  def __init__(self, keywords):
    self.messages = []
    self.state = self._Waiting
    self.data = []
    self.keywords = keywords

  def IsWhiteSpace(self, ttype):
    return ttype in [tokenize.COMMENT, token.INDENT, token.DEDENT,
                     token.NEWLINE, tokenize.NL]

  def __call__(self, ttype, tstring, stup, etup, line):
    del etup, line  # Unused.
    self.state(ttype, tstring, stup[0])

  def _Waiting(self, ttype, tstring, lineno):
    del lineno  # Unused.
    if ttype == tokenize.NAME and tstring in self.keywords:
      self.state = self._KeywordSeen

  def _KeywordSeen(self, ttype, tstring, lineno):
    del lineno  # Unused.
    if ttype == tokenize.OP and tstring == '(':
      self.data = []
      self.state = self._OpenSeen
    elif not self.IsWhiteSpace(ttype):
      self.state = self._Waiting

  def _OpenSeen(self, ttype, tstring, lineno):
    if ttype == tokenize.OP and (tstring in [')', ',']):
      value = ''.join(self.data)
      if value:
        self.messages.append((lineno, value))
      self.state = self._Waiting
    elif ttype == tokenize.STRING:
      self.data.append(ast.literal_eval(tstring))
    elif ttype == tokenize.NAME and tstring in self.keywords:
      # To support both Keyword1("str") and Keyword1(Keyword2("str")).
      self.state = self._KeywordSeen
    elif not self.IsWhiteSpace(ttype):
      self.state = self._Waiting


VOID_ELEMENTS = ['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                 'keygen', 'link', 'menuitem', 'meta', 'param', 'source',
                 'track', 'wbr']


class HTMLMessageParser(HTMLParser.HTMLParser, object):
  def __init__(self, html_classes):
    super(HTMLMessageParser, self).__init__()
    self.messages = []
    self.html_classes = set(html_classes)
    self.tags = []
    self.data = []
    self.in_keyword_tag = False

  def _MakeStartTag(self, tag, attrs, self_closing=False):
    attrs_str = ''.join(' %s="%s"' % (key, cgi.escape(value, quote=True))
                        for key, value in attrs)
    return '<%s%s%s>' % (tag, attrs_str, '/' if self_closing else '')

  def handle_starttag(self, tag, attrs):
    if self.in_keyword_tag:
      self.data.append(self._MakeStartTag(tag, attrs))

    if tag not in VOID_ELEMENTS:
      if self.in_keyword_tag:
        self.tags.append((tag, False))
      else:
        classes = ' '.join(value for key, value in attrs if key == 'class')
        classes = classes.split()
        is_keyword = any(cls in self.html_classes for cls in classes)
        self.tags.append((tag, is_keyword))
        if is_keyword:
          self.in_keyword_tag = True

  def handle_endtag(self, tag):
    if tag not in VOID_ELEMENTS:
      open_tag, is_keyword = self.tags.pop()
      if open_tag != tag:
        row, col = self.getpos()
        raise ValueError('%s,%s: Unexpected close tag, expected %s, got %s.' % (
            row, col, open_tag, tag))

      if is_keyword:
        msg = ''.join(self.data).strip()
        if msg:
          self.messages.append((self.getpos()[0], msg))
        self.data = []
        self.in_keyword_tag = False

    if self.in_keyword_tag:
      self.data.append('</%s>' % tag)

  def handle_startendtag(self, tag, attrs):
    if self.in_keyword_tag:
      self.data.append(self._MakeStartTag(tag, attrs, self_closing=True))

  def handle_data(self, data):
    if self.in_keyword_tag:
      self.data.append(re.sub(r'\s+', ' ', data))

  def handle_entityref(self, name):
    if self.in_keyword_tag:
      self.data.append('&%s;' % name)

  def handle_charref(self, name):
    if self.in_keyword_tag:
      self.data.append('&#%s;' % name)

  def close(self):
    super(HTMLMessageParser, self).close()
    if self.tags:
      raise ValueError('Found unclosed tags: %r' % ([t[0] for t in self.tags]))


def main():
  parser = argparse.ArgumentParser(
      description='pygettext -- Python equivalent of xgettext(1)')
  parser.add_argument(
      '-k', '--keyword', dest='keywords', action='append', default=[],
      help=('Keywords to look for in python source code. '
            'You can have multiple -k flags on the command line.'))
  parser.add_argument(
      '-c', '--class', dest='html_classes', action='append', default=[],
      help=('HTML classes to look for in HTML. '
            'You can have multiple -c flags on the command line.'))
  parser.add_argument(
      '-o', '--output', default='messages.pot', dest='output_file',
      help=('Rename the default output file from messages.pot to filename.  If'
            'filename is - then the output is sent to standard out.'))
  parser.add_argument(
      '-v', '--verbose', action='store_true',
      help='Print the names of the files being processed.')
  parser.add_argument(
      '-w', '--width', default=78, type=int,
      help='Set width of output to columns.')
  parser.add_argument(
      'input_file', nargs='+',
      help='Input file. Can either be python source code or HTML.')
  options = parser.parse_args()

  # calculate escapes
  MakeEscapes()

  messages = []
  for filename in options.input_file:
    if options.verbose:
      print 'Working on %s' % filename
    with open(filename) as fp:
      ext = os.path.splitext(filename)[1]
      if ext == '.py':
        eater = PyTokenEater(options.keywords)
        try:
          tokenize.tokenize(fp.readline, eater)
          messages.extend(((filename, lineno), msg)
                          for lineno, msg in eater.messages)
        except tokenize.TokenError as e:
          print >> sys.stderr, '%s: %s, line %d, column %d' % (
              e[0], filename, e[1][0], e[1][1])
      elif ext == '.html':
        parser = HTMLMessageParser(options.html_classes)
        try:
          parser.feed(fp.read())
          parser.close()
          messages.extend(((filename, lineno), msg)
                          for lineno, msg in parser.messages)
        except Exception as e:
          print >> sys.stderr, '%s: %s' % (filename, e)
      else:
        print >> sys.stderr, 'Unknown file type %s for file %s' % (
            ext, filename)

  if options.output_file == '-':
    fp = sys.stdout
    closep = 0
  else:
    fp = open(options.output_file, 'w')
    closep = 1
  try:
    WritePot(fp, messages, options.width)
  finally:
    if closep:
      fp.close()

if __name__ == '__main__':
  main()
