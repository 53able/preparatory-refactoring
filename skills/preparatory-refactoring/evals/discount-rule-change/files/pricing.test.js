const assert = require("assert");
const Module = require("module");
const origLoad = Module._load;
const users = { 1: { tier: 1 }, 2: { tier: 2 }, 3: { tier: 3, created: Date.now() - 1000 } };
Module._load = function (req, ...rest) {
  if (req === "./db") return { user: (id) => users[id] };
  return origLoad.call(this, req, ...rest);
};
const { price } = require("./pricing");
assert.strictEqual(price({ uid: 1, lines: [{ p: 1000, q: 2 }] }), 2000);
assert.strictEqual(price({ uid: 2, lines: [{ p: 1000, q: 2 }] }), 1800);
assert.strictEqual(price({ uid: 3, lines: [{ p: 1000, q: 2 }] }), 1200);
assert.strictEqual(price({ uid: 9, lines: [{ p: 100, q: 1 }] }), 100);
console.log("ok");
