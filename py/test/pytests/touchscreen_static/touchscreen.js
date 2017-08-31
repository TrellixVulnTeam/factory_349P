// Copyright 2017 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/**
 * API for touchscreen test.
 * @constructor
 * @param {string} container
 * @param {number} numColumns Number of columns.
 * @param {number} numRows Number of rows.
 * @param {number} maxRetries Number of retries.
 * @param {number} demoIntervalMsecs Interval (ms) to show drawing pattern.
 *     Non-positive value means no demo.
 * @param {boolean} e2eMode Perform end-to-end test or not (for touchscreen).
 * @param {boolean} spiralMode Blocks must be drawn in spiral order or not.
 */
var TouchscreenTest = function(
    container, numColumns, numRows, maxRetries, demoIntervalMsecs,
    e2eMode, spiralMode) {
  var _ = cros.factory.i18n.translation;
  this.container = container;
  this.numColumns = numColumns;
  this.numRows = numRows;
  this.maxRetries = maxRetries;
  this.e2eMode = e2eMode;
  this.spiralMode = spiralMode;

  this.expectSequence = [];
  this.tries = 0;

  this.previousBlockIndex = -1;
  this.expectBlockIndex = 0;
  this.tryFailed = false;

  this.indicatorLength = 4;
  this.demoIntervalMsecs = demoIntervalMsecs;
  console.log('demo interval: ' + demoIntervalMsecs);

  this.MSG_ANYORDER_INSTRUCTION =
      _('Draw blocks in any order; Esc to fail.');
  this.MSG_SPIRAL_INSTRUCTION =
      _('Draw blocks from upper-left corner in sequence; Esc to fail.');
  this.MSG_START_UPPER_LEFT = _('Please start drawing from upper-left corner.');
  this.MSG_OUT_OF_SEQUENCE =
      _('Fails to draw blocks in sequence. Please try again.');
  this.MSG_OUT_OF_SEQUENCE_MULTIPLE =
      _('Please leave your finger and restart from upper-left block.');
  this.MSG_LEAVE_EARLY = _('Finger leaving too early. Please try again.');
  this.MSG_CHECK_GODS_TOUCH =
      _('Test failed! Please test this panel carefully with Gods Touch test.');

  this.previousX = 0;
  this.previousY = 0;
  this.MOVE_TOLERANCE = 20;
};

/**
 * Creates a touchscreen test and runs it.
 * @param {string} container
 * @param {number} numColumns Number of columns.
 * @param {number} numRows Number of rows.
 * @param {number} maxRetries Number of retries.
 * @param {number} demoIntervalMsecs Interval (ms) to show drawing pattern.
 *     Non-positive value means no demo.
 * @param {boolean} e2eMode Perform end-to-end test or not (for touchscreen).
 * @param {boolean} spiralMode Blocks must be drawn in spiral order or not.
 */
function setupTouchscreenTest(
    container, numColumns, numRows, maxRetries, demoIntervalMsecs,
    e2eMode, spiralMode) {
  window.touchscreenTest = new TouchscreenTest(
      container, numColumns, numRows, maxRetries, demoIntervalMsecs,
      e2eMode, spiralMode);
  window.touchscreenTest.init();
}

/**
 * Initializes Touchscreen UI and touch sequence.
 */
TouchscreenTest.prototype.init = function() {
  this.setupFullScreenElement();
  this.expectSequence = this.generateTouchSequence();

  // Sanity check
  if (this.expectSequence.length != this.numColumns * this.numRows) {
    alert('generateTouchSequence() is buggy. The number of sequences ' +
          'is not equal to the number of blocks.');
    this.failTest();
  }

  if (this.spiralMode && this.demoIntervalMsecs > 0) {
    this.startDemo();
  }
};

/**
 * Initializes fullscreen div elements and sets fullscreen mode.
 *
 * The touch table contains xSegment by ySegment divs
 */
TouchscreenTest.prototype.setupFullScreenElement = function() {
  this.fullScreenElement = document.createElement('div');
  var fullScreen = this.fullScreenElement;
  fullScreen.className = 'touchscreen-full-screen';

  if(this.e2eMode) {
    fullScreen.addEventListener(
        'touchstart', this.touchStartListener.bind(this), false);
    fullScreen.addEventListener(
        'touchmove', this.touchMoveListener.bind(this), false);
    fullScreen.addEventListener(
        'touchend', this.touchEndListener.bind(this), false);
  }

  fullScreen.appendChild(createDiv('touchscreen-prompt', 'touchscreen_prompt'));

  fullScreen.appendChild(createDiv('', 'touchscreen_countdown_timer'))

  var touchscreenTable = createTable(this.numRows, this.numColumns, 'touch',
                                     'touchscreen-test-block-untested');
  fullScreen.appendChild(touchscreenTable);

  $(this.container).appendChild(fullScreen);

  this.restartTest();
  window.test.setFullScreen(true);
};

/**
 * Creates a touchscreen block test sequence.
 *
 * It starts from upper-left corner, draws the outer blocks in right, down,
 * left, up directions; then draws inner blocks till the center block is
 * reached.
 *
 * @return {Array<{blockIndex: number, directionX: number, directionY: number}>}
 *     Array of touchscreen block test sequence.
 */
TouchscreenTest.prototype.generateTouchSequence = function() {
  var xyToIndex = this.xyToIndex.bind(this);
  function impl(startX, startY, sizeX, sizeY) {
    var result = [];
    if (sizeX <= 0 || sizeY <= 0) {
      return result;
    }
    var x = startX;
    var y = startY;

    // Go right.
    for (; x < startX + sizeX; x++) {
      result.push({
        blockIndex: xyToIndex(x, y),
        directionX: 1,
        directionY: (x == startX + sizeX - 1) ? 1 : 0
      });
    }

    if (sizeY == 1) {
      return result;
    }

    // Go down. Skips the duplicate first point (same below).
    for (x--, y++; y < startY + sizeY; y++) {
      result.push({
        blockIndex: xyToIndex(x, y),
        directionX: (y == startY + sizeY - 1) ? -1 : 0,
        directionY: 1
      });
    }

    if (sizeX == 1) {
      return result;
    }

    // Go left.
    for (y--, x--; x >= startX; x--) {
      result.push({
        blockIndex: xyToIndex(x, y),
        directionX: -1,
        directionY: (x == startX) ? -1 : 0
      });
    }

    // Go up.
    for (x++, y--; y > startY; y--) {
      result.push({
        blockIndex: xyToIndex(x, y),
        directionX: (y == startY + 1) ? 1 : 0,
        directionY: -1
      });
    }

    return result.concat(impl(startX + 1, startY + 1, sizeX - 2, sizeY - 2));
  }
  return impl(0, 0, this.numColumns, this.numRows);
};

/**
 * Converts (x, y) block coordinates to block index.
 * @param {number} x x-coordinate
 * @param {number} y y-coordinate
 * @return {number} block index
 */
TouchscreenTest.prototype.xyToIndex = function(x, y) {
  return x + y * this.numColumns;
};

/**
 * Gets block index of the touch event.
 * @param {Event} touch Touch event.
 * @return {number} Block ID.
 */
TouchscreenTest.prototype.getBlockIndex = function(touch) {
  var col = Math.floor(touch.screenX / screen.width * this.numColumns);
  var row = Math.floor(touch.screenY / screen.height * this.numRows);
  return this.xyToIndex(col, row);
};

/**
 * Update previous x, y coordinates.
 * @param {Event} touch Touch event.
 */
TouchscreenTest.prototype.updatePreviousXY = function(touch) {
  this.previousX = touch.screenX;
  this.previousY = touch.screenY;
};

/**
 * Checks if the moving direction conforms to expectSequence.
 *
 * On conducting the God's touch test in OQC, circles are supposed to show up
 * exactly under the touching finger. If this is not the case, the touchscreen
 * is considered bad. It is desirable to catch the mis-location problem too in
 * this test. Such a bad panel may be caught in this test when a finger moves
 * in some direction, its reported coordinates jump in the other directions
 * when the finger moves to near around the problematic spot of the touchscreen.
 *
 * If directionX == 1, the finger is supposed to move to the right.
 * If directionX == -1, the finger is supposed to move to the left.
 * If directionX == 0, the finger is supposed to move in a vertical direction.
 * The rules apply to directionY in a similar way.
 * MOVE_TOLERANCE is used to allow a little deviation.
 *
 * @param {Event} touch Touch event.
 * @return {boolean} false if the moving direction is not correct.
 */
TouchscreenTest.prototype.checkDirection = function(touch) {
  var diffX = touch.screenX - this.previousX;
  var diffY = touch.screenY - this.previousY;
  this.updatePreviousXY(touch);
  if (this.expectBlockIndex < this.expectSequence.length) {
    var checkX = false;
    var checkY = false;
    switch (this.expectSequence[this.expectBlockIndex].directionX) {
      case 1:
        checkX = diffX + this.MOVE_TOLERANCE > 0;
        break;
      case 0:
        checkX = Math.abs(diffX) < this.MOVE_TOLERANCE;
        break;
      case -1:
        checkX = diffX < this.MOVE_TOLERANCE;
        break;
    }
    switch (this.expectSequence[this.expectBlockIndex].directionY) {
      case 1:
        checkY = diffY + this.MOVE_TOLERANCE > 0;
        break;
      case 0:
        checkY = Math.abs(diffY) < this.MOVE_TOLERANCE;
        break;
      case -1:
        checkY = diffY < this.MOVE_TOLERANCE;
        break;
    }
    return checkX && checkY;
  } else {
    return true;
  }
};

/**
 * Fails this try and if #retries is reached, fail the test.
 */
TouchscreenTest.prototype.failThisTry = function() {
  // Prevent marking multiple failure for a try.
  if (!this.tryFailed) {
    this.tryFailed = true;
    this.tries++;
    if (this.tries > this.maxRetries) {
      this.failTest();
    }
  }
};

function goofyTouchListener(handler_name, normalized_x, normalized_y) {
  var touch = {screenX: screen.width * normalized_x,
               screenY: screen.height * normalized_y};
  window.touchscreenTest[handler_name](touch);
}

TouchscreenTest.prototype.touchStartListener = function(event) {
  event.preventDefault();
  this.touchStartHandler(event.changedTouches[0]);
};

TouchscreenTest.prototype.touchMoveListener = function(event) {
  event.preventDefault();
  this.touchMoveHandler(event.changedTouches[0]);
};

TouchscreenTest.prototype.touchEndListener = function(event) {
  event.preventDefault();
  this.touchEndHandler(event.changedTouches[0]);
};

/**
 * Handles touchstart event.
 *
 * It checks if the touch starts from block (0, 0).
 * If not, prompt operator to do so.
 *
 * @param {Touch} touch
 */
TouchscreenTest.prototype.touchStartHandler = function(touch) {
  var touchBlockIndex = this.getBlockIndex(touch);
  this.updatePreviousXY(touch);

  if (this.spiralMode && touchBlockIndex != 0) {
    this.prompt(this.MSG_START_UPPER_LEFT);
    this.markBlock(touchBlockIndex, false);
    this.startTouch = false;
    this.failThisTry();
    return;
  }

  // Reset blocks for previous failure.
  if (this.tryFailed) {
    this.restartTest();
  }
  this.startTouch = true;
};

/**
 * Handles touchmove event.
 *
 * It'll check if the current block is the expected one.
 * If not, it'll prompt operator to restart from upper-left block.
 *
 * @param {Touch} touch
 */
TouchscreenTest.prototype.touchMoveHandler = function(touch) {
  var touchBlockIndex = this.getBlockIndex(touch);

  if (this.spiralMode && !this.checkDirection(touch)) {
    // Failed case. Ask the tester to verify with God's touch test.
    this.prompt(this.MSG_CHECK_GODS_TOUCH);
    this.markBlock(touchBlockIndex, false);
    this.failThisTry();
  }

  // Filter out move event of the same block.
  if (this.previousBlockIndex == touchBlockIndex) {
    return;
  }

  // No need to check block sequence if last one is out-of-sequence.
  if (!this.tryFailed &&
      (!this.spiralMode ||
           this.expectSequence[this.expectBlockIndex].blockIndex ==
           touchBlockIndex)) {
    if (this.spiralMode || !this.isBlockTested(touchBlockIndex)) {
      // Successful touched a expected block. Expecting next one.
      this.markBlock(touchBlockIndex, true);
      this.expectBlockIndex++;
      this.previousBlockIndex = touchBlockIndex;
      this.checkTestComplete();
    }
  } else {
    // Failed case. Either out-of-sequence touch or early finger leaving.
    // Show stronger prompt for drawing multiple unexpected blocks.
    this.prompt(
        this.tryFailed ? this.MSG_OUT_OF_SEQUENCE_MULTIPLE :
        this.MSG_OUT_OF_SEQUENCE);
    this.markBlock(touchBlockIndex, false);
    this.failThisTry();
    this.previousBlockIndex = touchBlockIndex;
  }
};

/**
 * Handles touchend event.
 * @param {Touch} touch
 */
TouchscreenTest.prototype.touchEndHandler = function(touch) {
  if (this.spiralMode) {
    var touchBlockIndex = this.getBlockIndex(touch);

    if (!this.tryFailed) {
      this.prompt(this.MSG_LEAVE_EARLY);
      this.failThisTry();
    }
    this.markBlock(touchBlockIndex, false);
  }
};

/**
 * Restarts the test.
 *
 * Resets test properties to default and blocks to untested.
 */
TouchscreenTest.prototype.restartTest = function() {
  this.prompt(this.spiralMode ?
              this.MSG_SPIRAL_INSTRUCTION :
              this.MSG_ANYORDER_INSTRUCTION);
  for (var i = 0; i < this.expectSequence.length; i++) {
    $('touch-' + i).className = 'touchscreen-test-block-untested';
  }
  this.previousBlockIndex = -1;
  this.expectBlockIndex = 0;
  this.tryFailed = false;
};

/**
 * Starts an animation for drawing pattern.
 */
TouchscreenTest.prototype.startDemo = function() {
  this.indicatorHead = this.expectBlockIndex;
  this.showDemoIndicator();
};

/**
 * Shows a hungry snake animation to guide operator to draw test pattern on the
 * touchscreen.
 *
 * It starts at the expected blocks (index 0). It changes the target block's CSS
 * to demo-0 (head indicator). Then the indicator block moves forward to next
 * expected block after demoIntervalMsecs. As indicator moving forward, it had
 * a tail with lighter color. And the block just behind the tail will be reset
 * to untested CSS.
 */
TouchscreenTest.prototype.showDemoIndicator = function() {
  // Last indicatorHead is ahead of expectSequence length by indicatorLength
  // because we want to sink the snake.
  if (this.indicatorHead >= this.expectSequence.length + this.indicatorLength) {
    clearTimeout(this.demoTimer);
    return;
  }

  for (var indicatorSegment = 0; indicatorSegment < this.indicatorLength;
       indicatorSegment++) {
    var index = this.indicatorHead - indicatorSegment;
    // Hide behind start point.
    if (index < this.expectBlockIndex) {
      break;
    }
    // Discard sink part.
    if (index >= this.expectSequence.length) {
      continue;
    }
    var block = $('touch-' + this.expectSequence[index].blockIndex);
    block.className = 'touchscreen-test-block-demo-' + indicatorSegment;
  }
  var cleanupIndex = this.indicatorHead - this.indicatorLength;
  if (cleanupIndex >= this.expectBlockIndex) {
    var untestedBlock =
        $('touch-' + this.expectSequence[cleanupIndex].blockIndex);
    untestedBlock.className = 'touchscreen-test-block-untested';
  }

  this.indicatorHead++;
  this.demoTimer = setTimeout(
      this.showDemoIndicator.bind(this), this.demoIntervalMsecs);
};

/**
 * Sets a block's test state.
 * @param {number} blockIndex
 * @param {boolean} passed false if the block is touched unexpectedly or the
 *     finger left too early.
 */
TouchscreenTest.prototype.markBlock = function(blockIndex, passed) {
  $('touch-' + blockIndex).className =
      'touchscreen-test-block-' + (passed ? 'tested' : 'failed');
};

/**
 * Gets a block's test state.
 * @param {number} blockIndex
 */
TouchscreenTest.prototype.isBlockTested = function(blockIndex) {
  return $('touch-' + blockIndex).className == 'touchscreen-test-block-tested';
};

/**
 * Checks if test is completed.
 * */
TouchscreenTest.prototype.checkTestComplete = function() {
  if (this.expectBlockIndex == this.expectSequence.length) {
    window.test.pass();
  }
};

/**
 * Fails the test and prints out all the failed items.
 */
TouchscreenTest.prototype.failTest = function() {
  // Returns an Array converted from the NodeList of the given class.
  function elements(className) {
    return Array.prototype.slice.call(
        document.getElementsByClassName(className));
  }

  var untestedBlocks = [];
  elements('touchscreen-test-block-untested').forEach(
    function(element) {
      untestedBlocks.push(element.id);
    }
  );
  var failedBlocks = [];
  elements('touchscreen-test-block-failed').forEach(
    function(element) {
      failedBlocks.push(element.id);
    }
  );

  this.failMessage = 'Touchscreen test failed.';
  if (failedBlocks.length) {
    this.failMessage += '  Failed blocks: ' + failedBlocks.join();
  }
  if (untestedBlocks.length) {
    this.failMessage += '  Untested blocks: ' + untestedBlocks.join();
  }
  window.test.fail(this.failMessage);
};

/**
 * Sets prompt message
 * @param {cros.factory.i18n.TranslationDict} message A message object
 *     containing i18n messages.
 */
TouchscreenTest.prototype.prompt = function(message) {
  goog.dom.safe.setInnerHtml(
      $('touchscreen_prompt'), cros.factory.i18n.i18nLabel(message));
};

/**
 * Creates a div element.
 * @param {string} className
 * @param {string} elementId
 * @return {Element} prompt div.
 */
function createDiv(className, elementId) {
  var prompt = document.createElement('div');
  prompt.className = className;
  prompt.id = elementId;
  return prompt;
}

/**
 * Creates a table element with specified row number and column number.
 * Each td in the table contains one div with id prefix-block_index
 * and the specified CSS class.
 * @param {number} rowNumber
 * @param {number} colNumber
 * @param {string} prefix
 * @param {string} className
 * @return {Element}
 */
function createTable(rowNumber, colNumber, prefix, className) {
  var table = document.createElement('table');
  table.className = 'touchscreen-test-table';
  var tableBody = document.createElement('tbody');
  var blockIndex = 0;
  for (var y = 0; y < rowNumber; ++y) {
    var row = document.createElement('tr');
    for (var x = 0; x < colNumber; ++x) {
      var cell = document.createElement('td');
      cell.id = prefix + '-' + blockIndex++;
      cell.className = className;
      cell.innerHTML = '&nbsp';
      row.appendChild(cell);
    }
    tableBody.appendChild(row);
  }
  table.appendChild(tableBody);
  return table;
}

/**
 * Fails the test.
 */
function failTest() {
  window.touchscreenTest.failTest();
}
