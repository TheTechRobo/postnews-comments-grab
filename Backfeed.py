from flask import Flask, request, abort

app = Flask(__name__)

@app.route("/", methods=["POST"])
def hello():
    print(request.get_json(force=True))
    if not request.json:
        print("hello")
        print(request.data)
        abort(400)
    print(request.json)
    a = request.json['items']
    with open("items", "a+") as file:
        file.write("\n" + " & ".join(a) + "\n")
    return "OK"

app.run(host="0.0.0.0")
