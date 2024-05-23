import json

print("Opening items")

with open("items") as file:
    for line in file:
        j = json.loads(line)
        for item in j:
            print(f"post:{item}")
