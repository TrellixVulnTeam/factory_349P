// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {RootState} from '@app/types';

import {NAME} from './constants';
import {DomeAppState} from './reducer';
import {AppName} from './types';

export const localState = (state: RootState): DomeAppState => state[NAME];

export const getCurrentApp =
  (state: RootState): AppName => localState(state).currentApp;
