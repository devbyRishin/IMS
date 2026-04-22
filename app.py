import os
from flask import Flask
from models import db
from routes import configure_routes

def create_app():
    app = Flask(__name__)
    app.secret_key = 'ims_workflow_secure_2026'
    import os

# At the top of create_app()
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'ims_v8.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'static', 'uploads')

    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    db.init_app(app)
    configure_routes(app)

    with app.app_context():
        db.create_all()

    return app


if __name__ == '__main__':
    create_app().run(port=5000, debug=True)
