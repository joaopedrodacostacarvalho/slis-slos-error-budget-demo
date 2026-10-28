from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/ship")
def ship():
    return jsonify({"status": "shipped"}), 200


@app.route("/health")
def health():
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
