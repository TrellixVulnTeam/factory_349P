// Copyright 2017 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

(() => {
  /**
   * Remove all children of root in the specified slot.
   * @param {!Element} root
   * @param {?string} slotName the specified slot name, if null, would remove
   *     all children without a slot.
   */
  const clearSlotContent = (root, slotName) => {
    const elements = root.querySelectorAll(
        slotName ? `:scope > [slot="${slotName}"]` : ':scope > :not([slot])');
    for (const element of elements) {
      element.remove();
    }
  };

  /**
   * Set the content of specified slot.
   * @param {!Element} root
   * @param {?string} slotName
   * @param {string} html
   * @param {boolean=} append
   */
  const setSlotContent = (root, slotName, html, append = false) => {
    if (!append) {
      clearSlotContent(root, slotName);
    }
    for (const element of Array.from(
             cros.factory.utils.createFragmentFromHTML(html, document)
                 .childNodes)) {
      let newElement = null;
      if (element instanceof Text) {
        if (slotName) {
          // For a top-level text node, we need a span wrapper to set the
          // "slot" attribute on it. This is not exactly equivalent to original
          // text node, since some formatting might change, but it should be
          // fine most of the time.
          // TODO(pihsun): We can fix this when display: contents is available.
          newElement = document.createElement('span');
          newElement.classList.add('inline');
          newElement.appendChild(element);
        } else {
          newElement = element;
        }
      } else if (element instanceof Element) {
        newElement = element;
      } else {
        continue;
      }
      if (slotName) {
        newElement.slot = slotName;
      }
      root.appendChild(newElement);
    }
  };

  /**
   * The document (templates.html) that contains the <template>.
   * This need to be get in the first pass when the script is run, and not in
   * the class methods.
   * @type {!Document}
   */
  const templateDoc = document.currentScript.ownerDocument;

  /**
   * A custom HTML element <test-template>.
   * The template has four sections: title, instruction (optional), state and
   * buttons.
   * The template would be available in JavaScript as window.template after
   * created.
   *
   * The instruction section also contains a progress bar, which is initially
   * hidden and can be shown with template.drawProgressBar().
   */
  class TestTemplate extends HTMLElement {
    constructor() {
      super();

      window.template = this;

      this.attachShadow({mode: 'open'});
      const template = templateDoc.getElementById('test-template');
      this.shadowRoot.appendChild(template.content.cloneNode(true));

      const markFailButton =
          this.shadowRoot.querySelector('#button-mark-failed');
      markFailButton.addEventListener('click', () => {
        window.test.userAbort();
      });
      if (window.test.invocation.getTestListEntry().disable_abort) {
        markFailButton.classList.add('disable-abort');
      }

      this.progressBar = null;
    }

    /**
     * Set the title section in the template.
     * @param {string} html
     */
    setTitle(html) {
      setSlotContent(this, 'title', html);
    }

    /**
     * Set the state section in the template. If append is true, would append
     * to the state section.
     * @param {string} html
     * @param {boolean=} append
     */
    setState(html, append = false) {
      const element = this.shadowRoot.querySelector('#state-container');
      const scrollAtBottom =
          element.scrollHeight - element.scrollTop === element.clientHeight;

      setSlotContent(this, null, html, append);

      if (append && scrollAtBottom) {
        element.scrollTop = element.scrollHeight - element.clientHeight;
      }
    }

    /**
     * Add a button to the button section with given label.
     * @param {!cros.factory.i18n.TranslationDict} label
     * @return {!HTMLButtonElement}
     */
    addButton(label) {
      const button = document.createElement('button');
      button.slot = 'extra-button';
      button.appendChild(cros.factory.i18n.i18nLabelNode(label));
      this.appendChild(button);
      return button;
    }

    /**
     * Set the instruction section in the template.
     * @param {string} html
     */
    setInstruction(html) {
      setSlotContent(this, 'instruction', html);
    }

    /**
     * Show the progress bar and set up the progress bar object.
     */
    drawProgressBar() {
      const container =
        this.shadowRoot.querySelector('#progress-bar-container');
      container.style.display = 'inline';

      const element = this.shadowRoot.querySelector('#progress-bar');
      const progressBar = new goog.ui.ProgressBar();
      progressBar.decorate(element);
      progressBar.setValue(0.0);
      this.progressBar = progressBar;
    }

    /**
     * Set the value of progress bar.
     * @param {number} value the percentage of progress, should be between 0
     *     and 100.
     */
    setProgressBarValue(value) {
      if (!this.progressBar) {
        throw Error(
            'Need to call drawProgressBar() before setProgressBarValue()!');
      }
      this.progressBar.setValue(value);

      const indicator =
        this.shadowRoot.querySelector('#progress-bar-indicator');
      indicator.innerText = value + '%';
    }
  }
  window.customElements.define('test-template', TestTemplate);
})();
