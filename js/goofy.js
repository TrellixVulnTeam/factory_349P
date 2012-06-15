// Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

goog.provide('cros.factory.Goofy');

goog.require('goog.crypt');
goog.require('goog.crypt.Sha1');
goog.require('goog.debug.ErrorHandler');
goog.require('goog.debug.FancyWindow');
goog.require('goog.debug.Logger');
goog.require('goog.dom');
goog.require('goog.dom.classes');
goog.require('goog.dom.iframe');
goog.require('goog.events');
goog.require('goog.events.EventHandler');
goog.require('goog.json');
goog.require('goog.math');
goog.require('goog.net.WebSocket');
goog.require('goog.net.XhrIo');
goog.require('goog.string');
goog.require('goog.style');
goog.require('goog.Uri');
goog.require('goog.ui.AdvancedTooltip');
goog.require('goog.ui.Checkbox');
goog.require('goog.ui.Dialog');
goog.require('goog.ui.Dialog.ButtonSet');
goog.require('goog.ui.MenuSeparator');
goog.require('goog.ui.PopupMenu');
goog.require('goog.ui.ProgressBar');
goog.require('goog.ui.Prompt');
goog.require('goog.ui.Select');
goog.require('goog.ui.SplitPane');
goog.require('goog.ui.tree.TreeControl');

cros.factory.logger = goog.debug.Logger.getLogger('cros.factory');

/**
 * @define {boolean} Whether to automatically collapse items once tests have
 *     completed.
 */
cros.factory.AUTO_COLLAPSE = false;

/**
 * Keep-alive interval for the WebSocket.  (Chrome times out
 * WebSockets every ~1 min, so 30 s seems like a good interval.)
 * @const
 * @type number
 */
cros.factory.KEEP_ALIVE_INTERVAL_MSEC = 30000;

/**
 * Width of the control panel, as a fraction of the viewport size.
 * @type number
 */
cros.factory.CONTROL_PANEL_WIDTH_FRACTION = 0.2;

/**
 * Minimum width of the control panel, in pixels.
 * @type number
 */
cros.factory.CONTROL_PANEL_MIN_WIDTH = 275;

/**
 * Height of the log pane, as a fraction of the viewport size.
 * @type number
 */
cros.factory.LOG_PANE_HEIGHT_FRACTION = 0.2;

/**
 * Minimum height of the log pane, in pixels.
 * @type number
 */
cros.factory.LOG_PANE_MIN_HEIGHT = 170;

/**
 * Makes a label that displays English (or optionally Chinese).
 * @param {string} en
 * @param {string=} zh
 */
cros.factory.Label = function(en, zh) {
    return '<span class="goofy-label-en">' + en + '</span>' +
      '<span class="goofy-label-zh">' + (zh || en) + '</span>';
};

/**
 * Makes control content that displays English (or optionally Chinese).
 * @param {string} en
 * @param {string=} zh
 * @return {Node}
 */
cros.factory.Content = function(en, zh) {
    var span = document.createElement('span');
    span.innerHTML = cros.factory.Label(en, zh);
    return span;
};

/**
 * Labels for items in system info.
 * @type Array.<Object.<string, string>>
 */
cros.factory.SYSTEM_INFO_LABELS = [
    {key: 'serial_number', label: cros.factory.Label('Serial Number')},
    {key: 'factory_image_version',
     label: cros.factory.Label('Factory Image Version')},
    {key: 'wlan0_mac', label: cros.factory.Label('WLAN MAC')},
    {key: 'kernel_version', label: cros.factory.Label('Kernel')},
    {key: 'ec_version', label: cros.factory.Label('EC')},
    {key: 'firmware_version', label: cros.factory.Label('Firmware')},
    {key: 'factory_md5sum', label: cros.factory.Label('Factory MD5SUM'),
     transform: function(value) {
            return value || cros.factory.Label('(no update)')
        }}
                                   ];

cros.factory.UNKNOWN_LABEL = '<span class="goofy-unknown">' +
    cros.factory.Label('Unknown') + '</span>';

/**
 * An item in the test list.
 * @typedef {{path: string, label_en: string, label_zh: string,
 *            kbd_shortcut: string, subtests: Array}}
 */
cros.factory.TestListEntry;

/**
 * A pending shutdown event.
 * @typedef {{delay_secs: number, time: number, operation: string,
 *            iteration: number, iterations: number }}
 */
cros.factory.PendingShutdownEvent;

/**
 * Public API for tests.
 * @constructor
 * @param {cros.factory.Invocation} invocation
 */
cros.factory.Test = function(invocation) {
    /**
     * @type cros.factory.Invocation
     */
    this.invocation = invocation;
};

/**
 * Passes the test.
 * @export
 */
cros.factory.Test.prototype.pass = function() {
    this.invocation.goofy.sendEvent(
        'goofy:end_test', {
            'status': 'PASSED',
            'invocation': this.invocation.uuid,
            'test': this.invocation.path
        });
    this.invocation.dispose();
};

/**
 * Fails the test with the given error message.
 * @export
 * @param {string} errorMsg
 */
cros.factory.Test.prototype.fail = function(errorMsg) {
    this.invocation.goofy.sendEvent('goofy:end_test', {
            'status': 'FAILED',
            'error_msg': errorMsg,
            'invocation': this.invocation.uuid,
            'test': this.invocation.path
        });
    this.invocation.dispose();
};

/**
 * Sends an event to the test backend.
 * @export
 * @param {string} subtype the event type
 * @param {string} data the event data
 */
cros.factory.Test.prototype.sendTestEvent = function(subtype, data) {
    this.invocation.goofy.sendEvent('goofy:test_ui_event', {
        'test': this.invocation.path,
        'invocation': this.invocation.uuid,
        'subtype': subtype,
        'data': data
        });
};

/**
 * UI for a single test invocation.
 * @constructor
 * @param {cros.factory.Goofy} goofy
 * @param {string} path
 */
cros.factory.Invocation = function(goofy, path, uuid) {
    /**
     * Reference to the Goofy object.
     * @type cros.factory.Goofy
     */
    this.goofy = goofy;

    /**
     * @type string
     */
    this.path = path;

    /**
     * UUID of the invocation.
     * @type string
     */
    this.uuid = uuid;

    /**
     * Test API for the invocation.
     */
    this.test = new cros.factory.Test(this);

    /**
     * The iframe containing the test.
     * @type HTMLIFrameElement
     */
    this.iframe = goog.dom.iframe.createBlank(new goog.dom.DomHelper(document));
    document.getElementById('goofy-main').appendChild(this.iframe);
    this.iframe.contentWindow.test = this.test;
};

/**
 * Disposes of the invocation (and destroys the iframe).
 */
cros.factory.Invocation.prototype.dispose = function() {
    if (this.iframe) {
        goog.dom.removeNode(this.iframe);
        this.goofy.invocations[this.uuid] = null;
        this.iframe = null;
    }
};

/**
 * The main Goofy UI.
 *
 * @constructor
 */
cros.factory.Goofy = function() {
    /**
     * The WebSocket we'll use to communicate with the backend.
     * @type goog.net.WebSocket
     */
    this.ws = new goog.net.WebSocket();

    /**
     * Whether we have opened the WebSocket yet.
     * @type boolean
     */
    this.wsOpened = false;

    /**
     * The UUID that we received from Goofy when starting up.
     * @type {?string}
     */
    this.uuid = null;

    /**
     * Whether the context menu is currently visible.
     * @type boolean
     */
    this.contextMenuVisible = false;

    /**
     * All tooltips that we have created.
     * @type Array.<goog.ui.AdvancedTooltip>
     */
    this.tooltips = [];

    /**
     * The test tree.
     */
    this.testTree = new goog.ui.tree.TreeControl('Tests');
    this.testTree.setShowRootNode(false);
    this.testTree.setShowLines(false);

    /**
     * A map from test path to the tree node for each test.
     * @type Object.<string, goog.ui.tree.BaseNode>
     */
    this.pathNodeMap = new Object();

    /**
     * A map from test path to the entry in the test list for that test.
     * @type Object.<string, cros.factory.TestListEntry>
     */
    this.pathTestMap = new Object();

    /**
     * Whether Chinese mode is currently enabled.
     *
     * TODO(jsalz): Generalize this to multiple languages (but this isn't
     * really necessary now).
     *
     * @type boolean
     */
    this.zhMode = false;

    /**
     * The tooltip for version number information.
     */
    this.infoTooltip = new goog.ui.AdvancedTooltip(
        document.getElementById('goofy-system-info-hover'));
    this.infoTooltip.setHtml('Version information not yet available.');

    /**
     * UIs for individual test invocations (by UUID).
     * @type Object.<string, cros.factory.Invocation>
     */
    this.invocations = {};

    /**
     * Eng mode prompt.
     * @type goog.ui.Dialog
     */
    this.engineeringModeDialog = null;

    /**
     * Shutdown prompt dialog.
     * @type goog.ui.Dialog
     */
    this.shutdownDialog = null;

    /**
     * Whether eng mode is enabled.
     * @type {boolean}
     */
    this.engineeringMode = false;

    /**
     * SHA1 hash of password to take UI out of operator mode.  If
     * null, eng mode is always enabled.  Defaults to an invalid '?',
     * which means that eng mode cannot be entered (will be set from
     * Goofy's shared_data).
     * @type {?string}
     */
    this.engineeringPasswordSHA1 = '?';

    var debugWindow = new goog.debug.FancyWindow('main');
    debugWindow.setEnabled(false);
    debugWindow.init();
    // Magic keyboard shortcuts.
    goog.events.listen(
        window, goog.events.EventType.KEYDOWN,
        function(event) {
            if (event.altKey && event.ctrlKey) {
                switch (String.fromCharCode(event.keyCode)) {
                case '0':
                    this.promptEngineeringPassword();
                    break;
                case '1':
                    debugWindow.setEnabled(true);
                    break;
                default:
                    // Nothing
                }
            }
        }, false, this);
};

/**
 * Initializes the split panes.
 */
cros.factory.Goofy.prototype.initSplitPanes = function() {
    var viewportSize = goog.dom.getViewportSize(goog.dom.getWindow(document));
    var mainComponent = new goog.ui.Component();
    var consoleComponent = new goog.ui.Component();
    var mainAndConsole = new goog.ui.SplitPane(
        mainComponent, consoleComponent,
        goog.ui.SplitPane.Orientation.VERTICAL);
    mainAndConsole.setInitialSize(
        viewportSize.height -
        Math.max(cros.factory.LOG_PANE_MIN_HEIGHT,
                 1 - cros.factory.LOG_PANE_HEIGHT_FRACTION));

    var controlComponent = new goog.ui.Component();
    var topSplitPane = new goog.ui.SplitPane(
        controlComponent, mainAndConsole,
        goog.ui.SplitPane.Orientation.HORIZONTAL);
    topSplitPane.setInitialSize(
        Math.max(cros.factory.CONTROL_PANEL_MIN_WIDTH,
                 viewportSize.width *
                 cros.factory.CONTROL_PANEL_WIDTH_FRACTION));
    topSplitPane.decorate(document.getElementById('goofy-splitpane'));

    mainComponent.getElement().id = 'goofy-main';
    consoleComponent.getElement().id = 'goofy-console';
    this.console = consoleComponent.getElement();
    this.main = mainComponent.getElement();

    var propagate = true;
    goog.events.listen(
        topSplitPane, goog.ui.Component.EventType.CHANGE,
        function(event) {
            if (!propagate) {
                // Prevent infinite recursion
                return;
            }

            propagate = false;
            mainAndConsole.setFirstComponentSize(
                mainAndConsole.getFirstComponentSize());
            propagate = true;

            var rect = mainComponent.getElement().getBoundingClientRect();
            this.sendRpc('get_shared_data', ['ui_scale_factor'],
                         function(uiScaleFactor) {
                             this.sendRpc('set_shared_data',
                                          ['test_widget_size',
                                           [rect.width * uiScaleFactor,
                                            rect.height * uiScaleFactor],
                                           'test_widget_position',
                                           [rect.left * uiScaleFactor,
                                            rect.top * uiScaleFactor]]);
                         });
        }, false, this);
    mainAndConsole.setFirstComponentSize(
        mainAndConsole.getFirstComponentSize());
    goog.events.listen(
        window, goog.events.EventType.RESIZE,
        function(event) {
            topSplitPane.setSize(
                goog.dom.getViewportSize(goog.dom.getWindow(document) ||
                                         window));
        });

    function onKey(e) {
        if (e.keyCode == goog.events.KeyCodes.ESC) {
            this.sendEvent('goofy:cancel_shutdown', {});
            // Wait for Goofy to reset the pending_shutdown data.
        }
    }
}

/**
 * Initializes the WebSocket.
 */
cros.factory.Goofy.prototype.initWebSocket = function() {
    goog.events.listen(this.ws, goog.net.WebSocket.EventType.OPENED,
                       function(event) {
                           this.logInternal('Connection to Goofy opened.');
                           this.wsOpened = true;
                       }, false, this);
    goog.events.listen(this.ws, goog.net.WebSocket.EventType.ERROR,
                       function(event) {
                           this.logInternal('Error connecting to Goofy.');
                       }, false, this);
    goog.events.listen(this.ws, goog.net.WebSocket.EventType.CLOSED,
                       function(event) {
                           if (this.wsOpened) {
                               this.logInternal('Connection to Goofy closed.');
                               this.wsOpened = false;
                           }
                       }, false, this);
    goog.events.listen(this.ws, goog.net.WebSocket.EventType.MESSAGE,
                       function(event) {
                           this.handleBackendEvent(event.message);
                       }, false, this);
    window.setInterval(goog.bind(this.keepAlive, this),
                       cros.factory.KEEP_ALIVE_INTERVAL_MSEC);
    this.ws.open("ws://" + window.location.host + "/event");
};

/**
 * Starts the UI.
 */
cros.factory.Goofy.prototype.init = function() {
    this.initLanguageSelector();
    this.initSplitPanes();

    // Listen for keyboard shortcuts.
    goog.events.listen(
        window, goog.events.EventType.KEYDOWN,
        function(event) {
            if (event.altKey || event.ctrlKey) {
                this.handleShortcut(String.fromCharCode(event.keyCode));
            }
        }, false, this);

    this.initWebSocket();
    this.sendRpc('get_test_list', [], this.setTestList);
    this.sendRpc('get_shared_data', ['system_info'], this.setSystemInfo);
    this.sendRpc(
        'get_shared_data', ['test_list_options'],
            function(options) {
                this.engineeringPasswordSHA1 =
                    options['engineering_password_sha1'];
                // If no password, enable eng mode, and don't
                // show the 'disable' link, since there is no way to
                // enable it.
                goog.style.showElement(document.getElementById(
                    'goofy-disable-engineering-mode'),
                    this.engineeringPasswordSHA1 != null);
                this.setEngineeringMode(this.engineeringPasswordSHA1 == null);
            });
};

/**
 * Sets up the language selector.
 */
cros.factory.Goofy.prototype.initLanguageSelector = function() {
    goog.events.listen(
        document.getElementById('goofy-language-selector'),
        goog.events.EventType.CLICK,
        function(event) {
            this.zhMode = !this.zhMode;
            this.updateLanguage();
            this.sendRpc('set_shared_data',
                         ['ui_lang', this.zhMode ? 'zh' : 'en']);
        }, false, this);

    this.updateLanguage();
    this.sendRpc('get_shared_data', ['ui_lang'], function(lang) {
            this.zhMode = lang == 'zh';
            this.updateLanguage();
        });
};

/**
 * Gets an invocation for a test (creating it if necessary).
 *
 * @param {string} path
 * @param {string} invocationUuid
 * @return the invocation, or null if the invocation has already been created
 *     and deleted.
 */
cros.factory.Goofy.prototype.getOrCreateInvocation = function(
    path, invocationUuid) {
    if (!(invocationUuid in this.invocations)) {
        cros.factory.logger.info('Creating UI for test ' + path +
                                 ' (invocation ' + invocationUuid);
        this.invocations[invocationUuid] =
            new cros.factory.Invocation(this, path, invocationUuid);
    }
    return this.invocations[invocationUuid];
};

/**
 * Updates language classes in the UI based on the current value of
 * zhMode.
 */
cros.factory.Goofy.prototype.updateLanguage = function() {
    goog.dom.classes.enable(document.body, 'goofy-lang-en', !this.zhMode);
    goog.dom.classes.enable(document.body, 'goofy-lang-zh', this.zhMode);
}

/**
 * Updates the system info tooltip.
 * @param systemInfo Object.<string, string>
 */
cros.factory.Goofy.prototype.setSystemInfo = function(systemInfo) {
    var table = [];
    table.push('<table id="goofy-system-info">');
    goog.array.forEach(cros.factory.SYSTEM_INFO_LABELS, function(item) {
            var value = systemInfo[item.key];
            var html;
            if (item.transform) {
                html = item.transform(value);
            } else {
                html = value == undefined ?
                    cros.factory.UNKNOWN_LABEL :
                    goog.string.htmlEscape(value);
            }
            table.push(
                       '<tr><th>' + item.label + '</th><td>' + html +
                       '</td></tr>');
        });
    table.push('</table>');
    this.infoTooltip.setHtml(table.join(''));
};

/**
 * Displays an alert.
 * @param {string} messageHtml
 */
cros.factory.Goofy.prototype.alert = function(messageHtml) {
    var dialog = new goog.ui.Dialog();
    dialog.setTitle('Alert');
    dialog.setButtonSet(goog.ui.Dialog.ButtonSet.createOk());
    dialog.setContent(messageHtml);
    dialog.setVisible(true);
    goog.dom.classes.add(dialog.getElement(), 'goofy-alert');
    this.positionOverConsole(dialog.getElement());
};

/**
 * Centers an element over the console.
 * @param {Element} element
 */
cros.factory.Goofy.prototype.positionOverConsole = function(element) {
    var consoleBounds = goog.style.getBounds(this.console.parentNode);
    var size = goog.style.getSize(element);
    goog.style.setPosition(
        element,
        consoleBounds.left + consoleBounds.width/2 - size.width/2,
        consoleBounds.top + consoleBounds.height/2 - size.height/2);
};

/**
 * Prompts to enter eng mode.
 */
cros.factory.Goofy.prototype.promptEngineeringPassword = function() {
    if (this.engineeringModeDialog) {
        this.engineeringModeDialog.setVisible(false);
        this.engineeringModeDialog.dispose();
        this.engineeringModeDialog = null;
    }
    if (!this.engineeringPasswordSHA1) {
        this.alert('No password has been set.');
        return;
    }
    if (this.engineeringMode) {
        this.setEngineeringMode(false);
        return;
    }

    this.engineeringModeDialog = new goog.ui.Prompt(
        'Password', '',
        goog.bind(function(text) {
            if (!text || text == '') {
                return;
            }
            var hash = new goog.crypt.Sha1();
            hash.update(text);
            var digest = goog.crypt.byteArrayToHex(hash.digest());
            if (digest == this.engineeringPasswordSHA1) {
                this.setEngineeringMode(true);
            } else {
                this.alert('Incorrect password.');
            }
        }, this));
    this.engineeringModeDialog.setVisible(true);
    goog.dom.classes.add(this.engineeringModeDialog.getElement(),
                         'goofy-engineering-mode-dialog');
    this.engineeringModeDialog.reposition();
    this.positionOverConsole(this.engineeringModeDialog.getElement());
};

/**
 * Sets eng mode.
 * @param {boolean} enabled
 */
cros.factory.Goofy.prototype.setEngineeringMode = function(enabled) {
    this.engineeringMode = enabled;
    goog.dom.classes.enable(document.body, 'goofy-engineering-mode', enabled);
};

/**
 * Closes any open dialog.
 */
cros.factory.Goofy.prototype.closeDialog = function() {
    if (this.dialog) {
        this.dialog.setVisible(false);
        this.dialog.dispose();
        this.dialog = null;
    }
};

/**
 * Deals with data about a pending reboot.
 * @param {cros.factory.PendingShutdownEvent} shutdownInfo
 */
cros.factory.Goofy.prototype.setPendingShutdown = function(shutdownInfo) {
    if (this.shutdownDialog) {
        this.shutdownDialog.setVisible(false);
        this.shutdownDialog.dispose();
        this.shutdownDialog = null;
    }
    if (!shutdownInfo || !shutdownInfo.time) {
        return;
    }
    this.closeDialog();

    var verbEn = shutdownInfo.operation == 'reboot' ?
        'Rebooting' : 'Shutting down';
    var verbZh = shutdownInfo.operation == 'reboot' ? '重開機' : '關機';

    var timesEn = shutdownInfo.iterations == 1 ? 'once' : (
        shutdownInfo.iteration + ' of ' + shutdownInfo.iterations + ' times');
    var timesZh = shutdownInfo.iterations == 1 ? '1次' : (
        shutdownInfo.iterations + '次' + verbZh + '測試中的第' +
        shutdownInfo.iteration + '次');

    this.shutdownDialog = new goog.ui.Dialog();
    this.shutdownDialog.setContent(
        '<p>' + verbEn + ' in <span class="goofy-shutdown-secs"></span> ' +
        'second<span class="goofy-shutdown-secs-plural"></span> (' + timesEn +
        ').<br>' +
        'To cancel, press the Escape key.</p>' +
        '<p>將會在<span class="goofy-shutdown-secs"></span>秒內' + verbZh +
        '（' + timesZh + '）.<br>按ESC鍵取消.</p>');

    var progressBar = new goog.ui.ProgressBar();
    progressBar.render(this.shutdownDialog.getContentElement());

    function tick() {
        var now = new Date().getTime() / 1000.0;

        var startTime = shutdownInfo.time - shutdownInfo.delay_secs;
        var endTime = shutdownInfo.time;
        var fraction = (now - startTime) / (endTime - startTime);
        progressBar.setValue(goog.math.clamp(fraction, 0, 1) * 100);

        var secondsLeft = 1 + Math.floor(Math.max(0, endTime - now));
        goog.array.forEach(
            goog.dom.getElementsByClass('goofy-shutdown-secs'), function(elt) {
                elt.innerHTML = secondsLeft;
            }, this);
        goog.array.forEach(
            goog.dom.getElementsByClass('goofy-shutdown-secs-plural'),
            function(elt) {
                elt.innerHTML = secondsLeft == 1 ? '' : 's';
            }, this);
    }

    var timer = new goog.Timer(20);
    goog.events.listen(timer, goog.Timer.TICK, tick, false, this);
    timer.start();

    goog.events.listen(this.shutdownDialog, goog.ui.Component.EventType.HIDE,
                       function(event) {
                           timer.dispose();
                       }, false, this);

    function onKey(e) {
        if (e.keyCode == goog.events.KeyCodes.ESC) {
            this.sendEvent('goofy:cancel_shutdown', {});
            // Wait for Goofy to reset the pending_shutdown data.
        }
    }
    goog.events.listen(this.shutdownDialog.getElement(),
                       goog.events.EventType.KEYDOWN, onKey, false, this);

    this.shutdownDialog.setButtonSet(null);
    this.shutdownDialog.setHasTitleCloseButton(false);
    this.shutdownDialog.setEscapeToCancel(false);
    goog.dom.classes.add(this.shutdownDialog.getElement(),
                         'goofy-shutdown-dialog');
    this.shutdownDialog.setVisible(true);
};

/**
 * Handles a keyboard shortcut.
 * @param {string} key the key that was depressed (e.g., 'a' for Alt-A).
 */
cros.factory.Goofy.prototype.handleShortcut = function(key) {
    for (var path in this.pathTestMap) {
        var test = this.pathTestMap[path];
        if (test.kbd_shortcut &&
            test.kbd_shortcut.toLowerCase() == key.toLowerCase()) {
            this.sendEvent('goofy:restart_tests', {path: path});
            return;
        }
    }
};

/**
 * Makes a menu item for a context-sensitive menu.
 *
 * TODO(jsalz): Figure out the correct logic for this and how to localize this.
 * (Please just consider this a rough cut for now!)
 *
 * @param {string} verbEn the action in English.
 * @param {string} verbZh the action in Chinese.
 * @param {string} adjectiveEn a descriptive adjective for the tests (e.g.,
 *     'failed').
 * @param {string} adjectiveZh the adjective in Chinese.
 * @param {number} count the number of tests.
 * @param {cros.factory.TestListEntry} test the name of the root node containing
 *     the tests.
 * @param {Object} handler the handler function (see goog.events.listen).
 * @param {boolean=} opt_adjectiveAtEnd put the adjective at the end in English
 *     (e.g., tests that have *not passed*)
 */
cros.factory.Goofy.prototype.makeMenuItem = function(
    verbEn, verbZh, adjectiveEn, adjectiveZh, count, test, handler,
    opt_adjectiveAtEnd) {

    var labelEn = verbEn + ' ';
    var labelZh = verbZh;
    if (!test.subtests.length) {
        // leaf node
        labelEn += (opt_adjectiveAtEnd ? '' : adjectiveEn) +
            ' test ' + test.label_en;
        labelZh += adjectiveZh + '測試';
    } else {
        labelEn += count + ' ' + (opt_adjectiveAtEnd ? '' : adjectiveEn) + ' ' +
            (count == 1 ? 'test' : 'tests');
        if (test.label_en) {
            labelEn += ' in "' + goog.string.htmlEscape(test.label_en) + '"';
        }

        labelZh += count + '個' + adjectiveZh;
        if (test.label_en || test.label_zh) {
            labelZh += ('在“' +
                goog.string.htmlEscape(test.label_en || test.label_zh) +
                '”裡面的');
        }
        labelZh += '測試';
    }

    if (opt_adjectiveAtEnd) {
        labelEn += ' that ' + (count == 1 ? 'has' : 'have') + ' not passed';
    }

    var item = new goog.ui.MenuItem(cros.factory.Content(labelEn, labelZh));
    item.setEnabled(count != 0);
    goog.events.listen(item, goog.ui.Component.EventType.ACTION,
                       handler, true, this);
    return item;
};

/**
 * Displays test logs in a modal dialog.
 * @param {Array.<string>} paths paths whose logs should be displayed.
 *    (The first entry should be the root; its name will be used as the
 *    title.)
 */
cros.factory.Goofy.prototype.showTestLogs = function(paths) {
    this.sendRpc('get_test_history', [paths], function(history) {
        var dialog = new goog.ui.Dialog();

        if (history.length) {
            var viewSize = goog.dom.getViewportSize(
                goog.dom.getWindow(document) || window);
            var maxWidth = viewSize.width * 0.75;
            var maxHeight = viewSize.height * 0.75;

            var content = [
                '<dl class="goofy-history" style="max-width: ' +
                maxWidth + 'px; max-height: ' + maxHeight + 'px">'
                           ];
            goog.array.forEach(history, function(item) {
                content.push('<dt class="goofy-history-item history-item-' +
                             item.state.status +
                             '">' + goog.string.htmlEscape(item.path) +
                             ' (run ' +
                             item.state.count + ')</dt>');
                content.push('<dd>' + goog.string.htmlEscape(item.log) +
                             '</dd>');
            }, this);
            content.push('</dl>');
            dialog.setContent(content.join(''));
        } else {
            dialog.setContent('<div class="goofy-history-none">' +
                              'No test runs have completed yet.</div>');
        }
        dialog.setTitle(
            'Logs for ' + (paths[0] == '' ? 'all tests' :
                           '"' + goog.string.htmlEscape(paths[0]) + '"'));
        dialog.setButtonSet(goog.ui.Dialog.ButtonSet.createOk())
        dialog.setVisible(true);
    });
};

/**
 * Displays a context menu for a test in the test tree.
 * @param {string} path the path of the test whose context menu should be
 *     displayed.
 * @param {Element} labelElement the label element of the node in the test
 *     tree.
 * @param {Array.<goog.ui.Control>=} extraItems items to prepend to the
 *     menu.
 */
cros.factory.Goofy.prototype.showTestPopup = function(path, labelElement,
                                                      extraItems) {
    this.contextMenuVisible = true;
    // Hide all tooltips so that they don't fight with the context menu.
    goog.array.forEach(this.tooltips, function(tooltip) {
            tooltip.setVisible(false);
        });

    var menu = new goog.ui.PopupMenu();

    if (extraItems && extraItems.length) {
        goog.array.forEach(extraItems, function(item) {
                menu.addChild(item, true);
            }, this);
        menu.addChild(new goog.ui.MenuSeparator(), true);
    }

    var numLeaves = 0;
    var numLeavesByStatus = {};
    var test = this.pathTestMap[path];
    var allPaths = [];
    function countLeaves(test) {
        allPaths.push(test.path);
        goog.array.forEach(test.subtests, function(subtest) {
                countLeaves(subtest);
            }, this);

        if (!test.subtests.length) {
            ++numLeaves;
            numLeavesByStatus[test.state.status] = 1 + (
                numLeavesByStatus[test.state.status] || 0);
        }
    }
    countLeaves(test);

    var restartOrRunEn = numLeavesByStatus['UNTESTED'] == numLeaves ?
        'Run' : 'Restart';
    var restartOrRunZh = numLeavesByStatus['UNTESTED'] == numLeaves ?
        '執行' : '重跑';
    if (numLeaves > 1) {
        restartOrRunEn += ' all';
        restartOrRunZh += '所有的';
    }
    menu.addChild(this.makeMenuItem(restartOrRunEn, restartOrRunZh,
                                    '', '',
                                    numLeaves, test,
                                    function(event) {
        this.sendEvent('goofy:restart_tests', {'path': path});
    }), true);
    if (test.subtests.length) {
        // Only show for parents.
        menu.addChild(this.makeMenuItem(
            'Restart', '重跑', 'not passed', '未成功',
            (numLeavesByStatus['UNTESTED'] || 0) +
            (numLeavesByStatus['ACTIVE'] || 0) +
            (numLeavesByStatus['FAILED'] || 0),
            test, function(event) {
                this.sendEvent('goofy:run_tests_with_status', {
                        'status': ['UNTESTED', 'ACTIVE', 'FAILED'],
                        'path': path
                    });
            }, /*opt_adjectiveAtEnd=*/true), true);
        menu.addChild(this.makeMenuItem(
            'Run', '執行', 'untested', '未測的',
            (numLeavesByStatus['UNTESTED'] || 0) +
            (numLeavesByStatus['ACTIVE'] || 0),
            test, function(event) {
                this.sendEvent('goofy:auto_run', {'path': path});
            }), true);
    }
    menu.addChild(new goog.ui.MenuSeparator(), true);
    // TODO(jsalz): This isn't quite right since it stops all tests.
    // But close enough for now.
    menu.addChild(this.makeMenuItem('Stop', '停止', 'active', '正在跑的',
                                    numLeavesByStatus['ACTIVE'] || 0,
                                    test, function(event) {
        this.sendEvent('goofy:stop');
    }), true);

    var item = new goog.ui.MenuItem('Show test logs...');
    item.setEnabled(test.state.status != 'UNTESTED');
    goog.events.listen(item, goog.ui.Component.EventType.ACTION,
                       function(event) {
                           this.showTestLogs(allPaths);
                       }, true, this);
    // Disable 'Show test logs...' for now since it is presented
    // behind the running test; we'd need to hide test to show it
    // properly.  TODO(jsalz): Re-enable.
    // menu.addChild(item, true);

    menu.render(document.body);
    menu.showAtElement(labelElement,
                     goog.positioning.Corner.BOTTOM_LEFT,
                     goog.positioning.Corner.TOP_LEFT);
    goog.events.listen(menu, goog.ui.Component.EventType.HIDE,
                       function(event) {
                           menu.dispose();
                           this.contextMenuVisible = false;
                       }, true, this);
};

/**
 * Updates the tooltip for a test based on its status.
 * The tooltip will be displayed only for failed tests.
 * @param {string} path
 * @param {goog.ui.AdvancedTooltip} tooltip
 * @param {goog.events.Event} event the BEFORE_SHOW event that will cause the
 *     tooltip to be displayed.
 */
cros.factory.Goofy.prototype.updateTestToolTip =
    function(path, tooltip, event) {
    var test = this.pathTestMap[path];

    tooltip.setHtml('')

    var errorMsg = test.state['error_msg'];
    if (test.state.status != 'FAILED' || this.contextMenuVisible || !errorMsg) {
        // Don't bother showing it.
        event.preventDefault();
    } else {
        // Show the last failure.
        var lines = errorMsg.split('\n');
        var html = ('Failure in "' + test.label_en + '":' +
                    '<div class="goofy-test-failure">' +
                    goog.string.htmlEscape(lines.shift()) + '</span>');

        if (lines.length) {
            html += ('<div class="goofy-test-failure-detail-link">' +
                     'Show more detail...</div>' +
                     '<div class="goofy-test-failure-detail">' +
                     goog.string.htmlEscape(lines.join('\n')) + '</div>');
        }

        tooltip.setHtml(html);

        if (lines.length) {
            var link = goog.dom.getElementByClass(
            'goofy-test-failure-detail-link', tooltip.getElement());
            goog.events.listen(
                link, goog.events.EventType.CLICK,
                function(event) {
                    goog.dom.classes.add(tooltip.getElement(),
                                         'goofy-test-failure-expanded');
                    tooltip.reposition();
            }, true, this);
        }
    }
};

/**
 * Sets up the UI for a the test list.  (Should be invoked only once, when
 * the test list is received.)
 * @param {cros.factory.TestListEntry} testList the test list (the return value
 *     of the get_test_list RPC call).
 */
cros.factory.Goofy.prototype.setTestList = function(testList) {
    cros.factory.logger.info('Received test list: ' +
        goog.debug.expose(testList));
    goog.style.showElement(document.getElementById('goofy-loading'), false);

    this.addToNode(null, testList);
    // expandAll is necessary to get all the elements to actually be
    // created right away so we can add listeners.  We'll collapse it later.
    this.testTree.expandAll();
    this.testTree.render(document.getElementById('goofy-test-tree'));

    var addListener = goog.bind(function(path, labelElement, rowElement) {
        var tooltip = new goog.ui.AdvancedTooltip(rowElement);
        tooltip.setHideDelayMs(1000);
        this.tooltips.push(tooltip);
        goog.events.listen(
            tooltip, goog.ui.Component.EventType.BEFORE_SHOW,
            function(event) {
                this.updateTestToolTip(path, tooltip, event);
            }, true, this)
        goog.events.listen(
            rowElement, goog.events.EventType.CONTEXTMENU,
            function(event) {
                this.showTestPopup(path, labelElement);
                event.stopPropagation();
                event.preventDefault();
            }, true, this);
        goog.events.listen(
            labelElement, goog.events.EventType.MOUSEDOWN,
            function(event) {
                this.showTestPopup(path, labelElement);
                event.stopPropagation();
                event.preventDefault();
            }, true, this);
    }, this);

    for (var path in this.pathNodeMap) {
        var node = this.pathNodeMap[path];
        addListener(path, node.getLabelElement(), node.getRowElement());
    }

    goog.array.forEach([goog.events.EventType.MOUSEDOWN,
                        goog.events.EventType.CONTEXTMENU],
        function(eventType) {
            goog.events.listen(
                document.getElementById('goofy-title'),
                eventType,
                function(event) {
                    var updateItem = new goog.ui.MenuItem(
                        cros.factory.Content('Update factory software',
                                             '更新工廠軟體'));
                    goog.events.listen(
                        updateItem, goog.ui.Component.EventType.ACTION,
                        function(event) {
                            this.sendEvent('goofy:update_factory', {});
                        }, true, this);

                    this.showTestPopup(
                        '', document.getElementById('goofy-logo-text'),
                        [updateItem]);

                    event.stopPropagation();
                    event.preventDefault();
                }, true, this);
        }, this);

    this.testTree.collapseAll();
    this.sendRpc('get_test_states', [], function(stateMap) {
        for (var path in stateMap) {
            if (!goog.string.startsWith(path, "_")) {  // e.g., __jsonclass__
                this.setTestState(path, stateMap[path]);
            }
        }
    });
};

/**
 * Sets the state for a particular test.
 * @param {string} path
 * @param {Object.<string, Object>} state the TestState object (contained in
 *     an event or as a response to the RPC call).
 */
cros.factory.Goofy.prototype.setTestState = function(path, state) {
    var node = this.pathNodeMap[path];
    if (!node) {
        cros.factory.logger.warning('No node found for test path ' + path);
        return;
    }

    var elt = this.pathNodeMap[path].getElement();
    var test = this.pathTestMap[path];
    test.state = state;

    // Assign the appropriate class to the node, and remove all other
    // status classes.
    goog.dom.classes.addRemove(
        elt,
        goog.array.filter(
            goog.dom.classes.get(elt),
            function(cls) {
                return goog.string.startsWith(cls, "goofy-status-") && cls
            }),
        'goofy-status-' + state.status.toLowerCase());

    if (state.status == 'ACTIVE') {
        // Automatically show the test if it is running.
        node.reveal();
    } else if (cros.factory.AUTO_COLLAPSE) {
        // If collapsible, then collapse it in 250ms if still inactive.
        if (node.getChildCount() != 0) {
            window.setTimeout(function(event) {
                    if (test.state.status != 'ACTIVE') {
                        node.collapse();
                    }
                }, 250);
        }
    }
};

/**
 * Adds a test node to the tree.
 * @param {goog.ui.tree.BaseNode} parent
 * @param {cros.factory.TestListEntry} test
 */
cros.factory.Goofy.prototype.addToNode = function(parent, test) {
    var node;
    if (parent == null) {
        node = this.testTree;
    } else {
        var label = '<span class="goofy-label-en">' +
            goog.string.htmlEscape(test.label_en) + '</span>';
        label += '<span class="goofy-label-zh">' +
            goog.string.htmlEscape(test.label_zh || test.label_en) + '</span>';
        if (test.kbd_shortcut) {
            label = '<span class="goofy-kbd-shortcut">Alt-' +
                goog.string.htmlEscape(test.kbd_shortcut.toUpperCase()) +
                '</span>' + label;
        }
        node = this.testTree.createNode(label);
        parent.addChild(node);
    }
    goog.array.forEach(test.subtests, function(subtest) {
            this.addToNode(node, subtest);
        }, this);

    node.setIconClass('goofy-test-icon');
    node.setExpandedIconClass('goofy-test-icon');

    this.pathNodeMap[test.path] = node;
    this.pathTestMap[test.path] = test;
    node.factoryTest = test;
};

/**
 * Sends an event to Goofy.
 * @param {string} type the event type (e.g., 'goofy:hello').
 * @param {Object} properties of event.
 */
cros.factory.Goofy.prototype.sendEvent = function(type, properties) {
    var dict = goog.object.clone(properties);
    dict.type = type;
    var serialized = goog.json.serialize(dict);
    cros.factory.logger.info('Sending event: ' + serialized);
    this.ws.send(serialized);
};

/**
 * Calls an RPC function and invokes callback with the result.
 * @param {Object} args
 * @param {Object=} callback
 */
cros.factory.Goofy.prototype.sendRpc = function(method, args, callback) {
    var request = goog.json.serialize({method: method, params: args, id: 1});
    cros.factory.logger.info('RPC request: ' + request);
    var factoryThis = this;
    goog.net.XhrIo.send(
        '/', function() {
            cros.factory.logger.info('RPC response for ' + method + ': ' +
                                     this.getResponseText());
            // TODO(jsalz): handle errors
            if (callback) {
                callback.call(
                    factoryThis,
                    goog.json.unsafeParse(this.getResponseText()).result);
            }
        },
        'POST', request);
};

/**
 * Sends a keepalive event if the web socket is open.
 */
cros.factory.Goofy.prototype.keepAlive = function() {
    if (this.ws.isOpen()) {
        this.sendEvent('goofy:keepalive', {'uuid': this.uuid});
    }
};

/**
 * Writes a message to the console log.
 * @param {string} message
 * @param {Object|Array.<string>|string=} opt_attributes attributes to add
 *     to the div element containing the log entry.
 */
cros.factory.Goofy.prototype.logToConsole = function(message, opt_attributes) {
    var div = goog.dom.createDom('div', opt_attributes);
    goog.dom.classes.add(div, 'goofy-log-line');
    div.appendChild(document.createTextNode(message));
    this.console.appendChild(div);
    // Scroll to bottom.  TODO(jsalz): Scroll only if already at the bottom,
    // or add scroll lock.
    var scrollPane = goog.dom.getAncestorByClass(this.console,
        'goog-splitpane-second-container');
    scrollPane.scrollTop = scrollPane.scrollHeight;
};

/**
 * Logs an "internal" message to the console (as opposed to a line from
 * console.log).
 */
cros.factory.Goofy.prototype.logInternal = function(message) {
    this.logToConsole(message, 'goofy-internal-log');
};

/**
 * Handles an event sends from the backend.
 * @param {string} jsonMessage the message as a JSON string.
 */
cros.factory.Goofy.prototype.handleBackendEvent = function(jsonMessage) {
    cros.factory.logger.info('Got message: ' + jsonMessage);
    var message = /** @type Object.<string, Object> */ (
        goog.json.unsafeParse(jsonMessage));

    if (message.type == 'goofy:hello') {
        if (this.uuid && message.uuid != this.uuid) {
            // The goofy process has changed; reload the page.
            cros.factory.logger.info('Incorrect UUID; reloading');
            window.location.reload();
            return;
        } else {
            this.uuid = message.uuid;
            // Send a keepAlive to confirm the UUID with the backend.
            this.keepAlive();
            // TODO(jsalz): Process version number information.
        }
    } else if (message.type == 'goofy:log') {
        this.logToConsole(message.message);
    } else if (message.type == 'goofy:state_change') {
        this.setTestState(message.path, message.state);
    } else if (message.type == 'goofy:set_html') {
        var invocation = this.getOrCreateInvocation(
            message.test, message.invocation);
        if (invocation) {
            if (!message.append && invocation.iframe.contentDocument.body) {
                goog.dom.removeChildren(invocation.iframe.contentDocument.body);
            }
            invocation.iframe.contentDocument.write(message['html']);
        }
    } else if (message.type == 'goofy:run_js') {
        var invocation = this.getOrCreateInvocation(
            message.test, message.invocation);
        if (invocation) {
            // We need to evaluate the code in the context of the content
            // window, but we also need to give it a variable.  Stash it
            // in the window and load it directly in the eval command.
            invocation.iframe.contentWindow.__goofy_args = message['args'];
            invocation.iframe.contentWindow.eval(
                'var args = window.__goofy_args;' +
                /** @type string */ (message['js']));
            delete invocation.iframe.contentWindow.__goofy_args;
        }
    } else if (message.type == 'goofy:call_js_function') {
        var invocation = this.getOrCreateInvocation(
            message.test, message.invocation);
        if (invocation) {
            var func = invocation.iframe.contentWindow.eval(message['name']);
            if (func) {
                func.apply(invocation.iframe.contentWindow, message['args']);
            } else {
                cros.factory.logger.severe('Unable to find function ' + func +
                                           ' in UI for test ' + message.test);
            }
        }
    } else if (message.type == 'goofy:destroy_test') {
        var invocation = this.invocations[message.invocation];
        if (invocation) {
            invocation.dispose();
        }
    } else if (message.type == 'goofy:system_info') {
        this.setSystemInfo(message['system_info']);
    } else if (message.type == 'goofy:pending_shutdown') {
        this.setPendingShutdown(
            /** @type {cros.factory.PendingShutdownEvent} */(message));
    }
};

goog.events.listenOnce(window, goog.events.EventType.LOAD, function() {
        window.goofy = new cros.factory.Goofy();
        window.goofy.init();
    });
