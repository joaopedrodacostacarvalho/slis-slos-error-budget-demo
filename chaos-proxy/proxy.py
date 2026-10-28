import os
import random

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

UPSTREAM = os.getenv("UPSTREAM_URL", "http://shipping:5001")
ERROR_RATE = 0.0  # 0.0 a 1.0
CHAOS_ENABLED = False


@app.route("/ship")
def proxy_ship():
    if CHAOS_ENABLED and random.random() < ERROR_RATE:
        return jsonify({"error": "chaos injected"}), 503

    # Encaminha para o shipping real
    resp = requests.get(f"{UPSTREAM}/ship", timeout=5)
    return resp.content, resp.status_code


@app.route("/chaos/on")
def chaos_on():
    global CHAOS_ENABLED, ERROR_RATE
    rate = float(request.args.get("rate", 0.3))
    CHAOS_ENABLED = True
    ERROR_RATE = rate
    return jsonify({"chaos": "enabled", "rate": rate}), 200


@app.route("/chaos/off")
def chaos_off():
    global CHAOS_ENABLED, ERROR_RATE
    CHAOS_ENABLED = False
    ERROR_RATE = 0.0
    return jsonify({"chaos": "disabled"}), 200


@app.route("/health")
def health():
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
