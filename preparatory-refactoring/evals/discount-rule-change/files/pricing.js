// pricing.js - used by cart and admin preview
const db = require("./db");

function price(c) {
  var r;
  var u = db.user(c.uid);
  var t = 0;
  for (var i = 0; i < c.lines.length; i++) {
    t = t + c.lines[i].p * c.lines[i].q;
  }
  if (u) {
    if (u.tier == 2) {
      // gold
      t = t - t * 0.1;
    } else {
      if (u.tier == 3) {
        t = t - t * 0.15;
      }
    }
    if (u.created && (Date.now() - u.created) < 30 * 24 * 3600 * 1000) {
      t = t - 500;
    }
  }
  if (t < 0) t = 0;
  // old coupon logic, disabled 2023
  // if (c.coupon) { t = t * 0.9 }
  r = Math.round(t);
  return r;
}

function unusedHelper(x) {
  return x * 2;
}

module.exports = { price };
