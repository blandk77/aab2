from flask import Flask
web = Flask(__name__)

@web.route('/')
def hello_world():
    return 'Status: Active...'


if __name__ == "__main__":
    web.run()
