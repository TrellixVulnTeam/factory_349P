// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Immutable from 'immutable';
import uuid from 'uuid/v4';

import {authorizedAxios, deepFilterKeys} from '../common/utils';
import {setAndShowErrorDialog} from '../error/actions';

import actionTypes from './actionTypes';
import {TaskStates} from './constants';

const changeTaskState = (taskID, state) => ({
  type: actionTypes.CHANGE_TASK_STATE,
  taskID,
  state,
});

class TaskQueue {
  constructor() {
    // Objects that cannot be serialized in the store.
    // The _taskBodies can't be serialized since it might contains File objects.
    this._taskBodies = {};
    this._taskResolves = {};
  }

  runTask = (description, method, url, body) => {
    return (dispatch, getState) => new Promise((resolve) => {
      const getTaskState = () => getState().get('task');

      const taskID = uuid();
      // if all tasks before succeed, start this task now.
      const startNow = getTaskState().get('tasks').every(
          (task) => task.get('state') === TaskStates.SUCCEEDED);

      this._taskBodies[taskID] = Immutable.fromJS(body);
      this._taskResolves[taskID] = resolve;
      dispatch({
        type: actionTypes.CREATE_TASK,
        taskID,
        description,
        method,
        url,
      });

      if (startNow) {
        dispatch(this._runTask(taskID));
      }
    });
  }

  dismissTask = (taskID) => (dispatch) => {
    delete this._taskBodies[taskID];
    delete this._taskResolves[taskID];
    dispatch({
      type: actionTypes.DISMISS_TASK,
      taskID,
    });
  };

  _runTask = (taskID) => async (dispatch, getState) => {
    const getTaskState = () => getState().get('task');

    dispatch(changeTaskState(taskID, TaskStates.RUNNING));

    const task = getTaskState().getIn(['tasks', taskID]);
    const body = this._taskBodies[taskID];

    try {
      const client = authorizedAxios();

      // go through the body and upload files first
      const fileFields = deepFilterKeys(body, (v) => v instanceof File);

      let data = body;
      // TODO(pihsun): Add upload progress for file upload.
      for (const path of fileFields) {
        const file = body.getIn(path);
        const formData = new FormData();
        formData.append('file', file);
        const response = await authorizedAxios().post('/files/', formData);
        data = data.withMutations((m) => {
          const key = path.last();
          m.deleteIn(path);
          // replace `${key}` with `${key}Id` and set it to the file ID
          m.setIn(path.pop().push(`${key}Id`), response.data.id);
        });
      }

      // send the end request
      const response = await client.request({
        url: task.get('url'),
        method: task.get('method'),
        data,
      });

      this._taskResolves[taskID]({response, cancel: false});

      // if all sub-tasks succeeded, mark it as succeeded, and start the next
      // task.
      dispatch(changeTaskState(taskID, TaskStates.SUCCEEDED));

      // find the first waiting task and start it
      const nextTaskEntry = getTaskState().get('tasks').findEntry(
          (task) => task.get('state') === TaskStates.WAITING);
      if (nextTaskEntry) {
        dispatch(this._runTask(nextTaskEntry[0]));
      }
    } catch (error) {
      // if any sub-task above failed, display the error message
      const {response} = error;
      if (response) {
        const {data} = response;
        const responseText =
            typeof(data) === 'string' ? data : JSON.stringify(data);
        dispatch(setAndShowErrorDialog(
            `${error.message}\n\n${responseText}`));
      } else {
        // Some unexpected error that is not server-side happened, probably a
        // bug in the task code.
        console.error(error);
        dispatch(setAndShowErrorDialog(`Unexpected Dome error: ${error}`));
      }
      // mark the task as failed
      dispatch(changeTaskState(taskID, TaskStates.FAILED));
    }
  };

  cancelWaitingTaskAfter = (taskID) => (dispatch, getState) => {
    // TODO(pihsun): probably need a better action name.
    // This action tries to cancel all waiting or failed tasks below and
    // include taskID.
    const getTaskState = () => getState().get('task');

    const tasks = getTaskState().get('tasks');
    const toCancelTasks =
        tasks.skipUntil((unusedTask, id) => id === taskID).filter((task) => {
          const state = task.get('state');
          return state === TaskStates.WAITING || state === TaskStates.FAILED;
        }).keySeq().reverse();

    // cancel all tasks below and include the target task
    for (const taskID of toCancelTasks) {
      this._taskResolves[taskID]({cancel: true});
      dispatch(this.dismissTask(taskID));
    }
  };
};

const taskQueue = new TaskQueue();
const {runTask, dismissTask, cancelWaitingTaskAfter} = taskQueue;

export {runTask, dismissTask, cancelWaitingTaskAfter};
