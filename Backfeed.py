from flask import Flask, request, abort

import json

app = Flask(__name__)

@app.route("/", methods=["POST"])
def hello():
    request.get_json(force=True)
    if not request.json:
        print("hello")
        print(request.data)
        abort(400)
    if not request.json['items']:
        # no items received
        return "OK"
    print(request.json)
    a = request.json['items']
    with open("items", "a+") as file:
        file.write(json.dumps(a)+"\n")
    return "OK"

app.run(host="0.0.0.0")
