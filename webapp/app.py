from canonicalwebteam.flask_base.app import FlaskBase
from flask import render_template
from webapp.login.views import login_blueprint

# Rename your project below
app = FlaskBase(
    __name__,
    "anbox-cloud.io",
    template_folder="../templates",
    static_folder="../static",
    template_404="404.html",
    template_500="500.html",
)
app.register_blueprint(login_blueprint(app))

@app.route("/")
def index():
    return render_template("index.html")


