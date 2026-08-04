// SPDX-License-Identifier: CPAL-1.0
// Original concept, product design, and independent project initiated by Ting (peanutsuee).
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(id = "") {
    this.id = id;
    this.textContent = "";
    this.attributes = {};
    this.children = [];
    this.listeners = new Map();
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  replaceChildren(...children) {
    this.children = children;
  }

  append(child) {
    this.children.push(child);
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  dispatch(type) {
    const listener = this.listeners.get(type);
    if (listener) listener();
  }
}

const viewerPath = path.join(
  __dirname,
  "..",
  "src",
  "remember_me",
  "mcp",
  "asset-viewer.html",
);
const html = fs.readFileSync(viewerPath, "utf8");
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/u);
assert.ok(scriptMatch, "embedded Viewer script must exist");
const script = scriptMatch[1];

for (const forbidden of [
  "innerHTML",
  "insertAdjacentHTML",
  "eval(",
  "new Function",
  "http://",
  "https://",
]) {
  assert.equal(script.includes(forbidden), false, `forbidden source: ${forbidden}`);
}

const elements = new Map(
  [
    "asset-image",
    "asset-title",
    "asset-file",
    "asset-details",
    "asset-tags",
  ].map((id) => [id, new Element(id)]),
);
const windowListeners = new Map();
const posted = [];
const parent = {
  postMessage(message, targetOrigin) {
    posted.push({ message, targetOrigin });
  },
};
const windowMock = {
  parent,
  addEventListener(type, listener) {
    windowListeners.set(type, listener);
  },
};
const documentMock = {
  getElementById(id) {
    return elements.get(id);
  },
  createElement() {
    return new Element();
  },
};

vm.runInNewContext(script, {
  document: documentMock,
  Map,
  Object,
  String,
  window: windowMock,
});

assert.equal(posted.length, 1);
const initialize = posted[0].message;
assert.equal(initialize.jsonrpc, "2.0");
assert.equal(initialize.id, 1);
assert.equal(initialize.method, "ui/initialize");
assert.equal(initialize.params.protocolVersion, "2026-01-26");
assert.equal(initialize.params.appInfo.name, "Remember-Me asset viewer");
assert.equal(Object.keys(initialize.params.appCapabilities).length, 0);

const receive = windowListeners.get("message");
assert.ok(receive, "Viewer must listen for Host messages");
receive({
  source: parent,
  data: {
    jsonrpc: "2.0",
    id: initialize.id,
    result: { protocolVersion: "2026-01-26", hostInfo: { name: "test" } },
  },
});
assert.equal(posted.length, 2);
assert.equal(posted[1].message.jsonrpc, "2.0");
assert.equal(posted[1].message.method, "ui/notifications/initialized");
assert.equal(Object.keys(posted[1].message.params).length, 0);

const validResult = {
  _meta: {
    remember_me: {
      asset: {
        title: "Dusk memory",
        original_filename: "dusk.png",
        width: 640,
        height: 480,
        mime_type: "image/png",
        tags: ["archive", "evening"],
      },
      image: {
        mime_type: "image/png",
        data: "c2FmZS1pbWFnZQ==",
      },
    },
  },
};

const untouchedTitle = elements.get("asset-title").textContent;
receive({
  source: {},
  data: {
    jsonrpc: "2.0",
    method: "ui/notifications/tool-result",
    params: validResult,
  },
});
assert.equal(elements.get("asset-title").textContent, untouchedTitle);

receive({
  source: parent,
  data: {
    jsonrpc: "2.0",
    type: "ui/notifications/tool-result",
    params: validResult,
  },
});
assert.equal(elements.get("asset-title").textContent, untouchedTitle);

for (const method of [
  "ui/notifications/tool-input",
  "ui/notifications/tool-input-partial",
  "ui/notifications/host-context-changed",
]) {
  receive({
    source: parent,
    data: {
      jsonrpc: "2.0",
      method,
      params: {},
    },
  });
  assert.equal(elements.get("asset-title").textContent, untouchedTitle);
}

receive({
  source: parent,
  data: {
    jsonrpc: "2.0",
    method: "ui/notifications/tool-result",
    params: validResult,
  },
});
assert.equal(elements.get("asset-title").textContent, "Dusk memory");
assert.equal(elements.get("asset-file").textContent, "dusk.png");
assert.equal(elements.get("asset-details").textContent, "640 x 480 | image/png");
assert.deepEqual(
  elements.get("asset-tags").children.map((item) => item.textContent),
  ["archive", "evening"],
);
assert.equal(
  elements.get("asset-image").attributes.src,
  "data:image/png;base64,c2FmZS1pbWFnZQ==",
);
elements.get("asset-image").dispatch("load");
assert.equal(elements.get("asset-image").attributes["data-state"], "ready");

receive({
  source: parent,
  data: {
    jsonrpc: "2.0",
    method: "ui/notifications/tool-result",
    params: { content: [] },
  },
});
assert.equal(elements.get("asset-title").textContent, "Viewer unavailable");
assert.equal(
  elements.get("asset-details").textContent,
  "The image result was missing or invalid.",
);

receive({
  source: parent,
  data: {
    jsonrpc: "2.0",
    method: "ui/notifications/tool-result",
    params: validResult,
  },
});
elements.get("asset-image").dispatch("error");
assert.equal(elements.get("asset-title").textContent, "Viewer unavailable");
assert.equal(
  elements.get("asset-details").textContent,
  "The privacy-cleaned image could not be decoded.",
);

const failedElements = new Map(
  [
    "asset-image",
    "asset-title",
    "asset-file",
    "asset-details",
    "asset-tags",
  ].map((id) => [id, new Element(id)]),
);
const failedListeners = new Map();
const failedPosted = [];
const failedParent = {
  postMessage(message) {
    failedPosted.push(message);
  },
};
const failedWindow = {
  parent: failedParent,
  addEventListener(type, listener) {
    failedListeners.set(type, listener);
  },
};
vm.runInNewContext(script, {
  document: {
    getElementById(id) {
      return failedElements.get(id);
    },
    createElement() {
      return new Element();
    },
  },
  Map,
  Object,
  String,
  window: failedWindow,
});
failedListeners.get("message")({
  source: failedParent,
  data: {
    jsonrpc: "2.0",
    id: failedPosted[0].id,
    error: { code: -32603, message: "internal detail must not render" },
  },
});
assert.equal(failedElements.get("asset-title").textContent, "Viewer unavailable");
assert.equal(
  failedElements.get("asset-details").textContent,
  "The viewer host could not be initialized.",
);
assert.equal(
  failedElements.get("asset-details").textContent.includes("internal detail"),
  false,
);

console.log("viewer protocol simulation passed");
