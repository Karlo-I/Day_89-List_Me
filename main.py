from flask import Flask,render_template, redirect, url_for, request, flash, abort
from flask_bootstrap import Bootstrap
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, login_user, logout_user, login_required, current_user, LoginManager
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
import os, logging
from dotenv import load_dotenv
from datetime import datetime, timezone
from forms import RegisterForm, LoginForm
from functools import wraps

# Setup .env password
load_dotenv()

# ------------- Setup Flask app --------------#
app = Flask(__name__)

# Setup app security and initialise Flask-Bootstrap extension
app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
bootstrap = Bootstrap(app)

# Configure Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id): # User_loader callback - complements Flask-Login
    return User.query.get_or_404(int(user_id))

# ------------- Setup SQL database --------------#
class Base(DeclarativeBase):
    pass
app.config["SQLALCHEMY_DATABASE_URI"] = 'sqlite:///todo.db'
db = SQLAlchemy(model_class=Base) # creates Flask extension
db.init_app(app) # initialise the app with the extension

# ------------- Configure DB Tables --------------#
class Item(db.Model):
    __tablename__ = "todo_list"
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    todo = db.Column(db.String(250), unique=True, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)  # New column to track soft deletion
    completed = db.Column(db.Boolean, default=False)  # New column to track task completion

    __table_args__ = (db.UniqueConstraint('owner_id', 'todo', name='unique_owner_todo'),)

    item_owner = relationship("User", back_populates="owner")

class User(db.Model, UserMixin): # UserMixin includes a 'get_id' method so there's no need to add manually
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))
    name = db.Column(db.String(100))
    owner = relationship("Item", back_populates="item_owner")

    def __init__(self, email, name, password):
        self.email = email
        self.name = name
        self.password = password

    # Add is_active method to define whether the user is active
    def is_active(self):
        return True  # Default implementation assuming all users are active

# Create a table schema in the database
with app.app_context():
    db.create_all()

# Create admin-only decorator
def admin_only(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # If id is not 1 then return abort with 403 error, otherwise continue w/ the route function
        if current_user.id != 1:
            return abort(403)
        return f(*args, **kwargs)
    return decorated_function

# ------------- Setup Home, Register, Login and Logout tabs --------------#

@app.route("/", methods=["GET"])
def home():
    print("Home route hit!") # Debug print statement
    if current_user.is_authenticated:
        # If the user is logged in, redirect them to the index page (user's page with their to-do list)
        return redirect(url_for("index", name=current_user.name))
    else:
        # If the user is not logged in, render the landing page
        return render_template("landing.html") # Landing page (login page, etc.)

@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        # Debugging: Check if form is validated and fields have data
        print(f"Form data: {form.email.data}, {form.name.data}, {form.password.data}")

        # Check if user's email is already present in the database
        result = db.session.execute(db.select(User).where(User.email == form.email.data))
        user = result.scalar()

        if user:
            flash("You're signed up, please log in with your details.")
            return redirect(url_for("login"))

        # Hash user's password when adding a new user is successful.
        hash_and_salted_password = generate_password_hash(
            form.password.data,
            method='pbkdf2:sha256',
            salt_length=8
        )

        new_user = User(
            email=form.email.data,
            name=form.name.data,
            password=hash_and_salted_password
        )

        try:
            db.session.add(new_user)
            db.session.commit()
            # Log the user in after successful registration
            login_user(new_user)
            flash("Registration successful! Please log in with your details.")
            return redirect(url_for("login"))  # Redirect to login after registration
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred while creating your account: {str(e)}")
            return redirect(url_for("register"))

    return render_template("register.html", form=form, current_user=current_user)

@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()

    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data

        # Check if email and password are non-empty before proceeding
        if not email or not password:
            flash("Both fields are required", "error")
            return redirect(url_for("login"))

        try:
            # Query the user by email
            result = db.session.execute(db.select(User).where(User.email == email))
            user = result.scalar()

            # Check if user exist in the database
            if not user:
                flash("That email does not exist, please try again.")
                return redirect(url_for("login"))

            # Verify password using check_password_hash
            if not check_password_hash(user.password, password):
                flash("Password incorrect, please try again.")
                return redirect(url_for("login"))

            # Log the user in if credentials are valid
            login_user(user, remember=True)  # Keep the user logged in across sessions
            return redirect(url_for("home"))

        except Exception as e:
            # Handle any unexpected errors
            flash(f"An error occurred while logging in: {e}")
            return redirect(url_for("login"))

    return render_template("login.html", form=form, current_user=current_user)

@app.route("/logout", methods=["GET"])
@login_required  # Ensure only logged-in users can log out
def logout():
    logout_user()
    return redirect(url_for("home"))

@app.route("/index/<name>", methods=["GET"])
@login_required # Ensure only logged-in users can view the to-do list
def index(name):
    # Fetch the user by name, assuming you have a User model
    user = User.query.filter_by(name=name).first()

    if user is None:
        # Handle case where user does not exist
        abort(404)  # or return an error message

    # Fetch the user's to-do list from the database
    result = db.session.execute(db.select(Item).filter(
        Item.owner_id == current_user.id,
        Item.completed == False, # Exclude completed tasks
        Item.deleted_at.is_(None) # Exclude deleted items
    ))
    todo_list = result.scalars().all()

    # Optionally, fetch deleted items if the current user is the admin (id == 1)
    if current_user.id == 1: # Admin only
        deleted_result = db.session.execute(db.select(Item).filter(Item.deleted_at.is_not(None)))  # Deleted items
        deleted_todo_list = deleted_result.scalars().all()
    else:
        deleted_todo_list = []

    return render_template("index.html", current_user=current_user, todo_list=todo_list, deleted_todo_list=deleted_todo_list)

@app.route("/add", methods=["GET", "POST"])
@login_required  # Ensure only logged-in users can add items
def add():
    if request.method == "POST":
        todo_item = request.form["Item to Add in the List"] # This needs to match the input name in add.html
        due_date_str = request.form["due_date"]  # Get the due_date as a string (yyyy-mm-dd)

        # Convert the due_date string to a datetime object (only date in this case)
        due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()

        if todo_item:
            # Create item to add to the database
            item_to_add = Item(
                todo = todo_item,
                due_date = due_date,
                owner_id = current_user.id # Set the owner_id to the currently logged-in user's ID
            )
            try:
                # Add item in the database
                db.session.add(item_to_add)
                db.session.commit()
                return redirect(url_for("home"))

            except IntegrityError:
                db.session.rollback() # Rollback the session in case of error
                if current_user.id == 1:  # Admin only
                    flash("This item already exists in the record. Please choose a different one or retrieve from the delete items.")
                    flash("Admin Issue. As the admin you should only be allowed to restore your previously delete item but not of others")
                    return redirect(url_for("home"))
                else:
                    flash("Admin Issue. User is currently not allowed to type in another user's entry or the user's previously deleted entry at the moment.")
                    return redirect(url_for("home"))

        else:
            flash("Item is required.")
            return redirect(url_for("home"))

    return render_template("index.html") # Render the same homepage template for adding an item

@app.route("/delete", methods=["GET", "POST"])
def delete_item():
    if request.method == "POST":
        item_id = request.form.get("item_id") # Get the item ID (a hidden input field) from the form

        if not item_id:
            # Handle case where item_id is missing
            flash("Item ID is required")
            return redirect(url_for("home"))

        # Fetch the item from the database using item_id
        item = Item.query.get(item_id)  # Fetch item by ID. If item is not found, it returns None.
        if not item:
            flash("Item not found!")
            return redirect(url_for("home"))

        try:
            # Soft delete: Set the deleted_at timestamp instead of permanently deleting the item
            item.deleted_at = datetime.now(timezone.utc)  # Mark the item as deleted by setting the timestamp
            db.session.commit()

            flash("Item deleted successfully.")
            return redirect(url_for("home"))

        except (ValueError, KeyError, SQLAlchemyError) as e:
            logging.error(f"Error occurred while declaring item: {e}") # Logs the error message
            flash("Error occurred while deleting the item!")
            return redirect(url_for("home"))

    # For GET requests (confirmation), we need to fetch the item
    item_id = request.args.get("item_id") # Get the item_id from the URL (via GET request)
    if item_id:
        item = db.get_or_404(Item, item_id)
        # flash("You are about to delete this item.") # Ensures an item is not deleted inadvertently
        return render_template("delete.html", item=item) # Pass the item to the template
    else:
        flash("Invalid item ID!")
        return redirect(url_for("home"))

@app.route("/mark_completed", methods=["POST"])
def mark_completed():
    # Get the list of item IDs to delete from the form
    item_ids_to_complete = request.form.getlist("items_to_complete")

    # Convert the item IDs to integers
    item_ids_to_complete = [int(item_id) for item_id in item_ids_to_complete]

    # Fetch the items from the database and delete them
    items_to_mark_complete = Item.query.filter(Item.id.in_(item_ids_to_complete)).all()
    for item in items_to_mark_complete:
        item.completed = True # Set the completed flag to True

    # Commit the changes to the database
    db.session.commit()

    flash("Selected items marked as completed.")
    return redirect(url_for("index", name=current_user.name))


@app.route('/edit_item/<int:item_id>', methods=['GET', 'POST'])
def edit_item(item_id):
    item = Item.query.get_or_404(item_id)

    if request.method == 'POST':
        # Get the updated values from the form
        updated_todo = request.form['todo_item']
        updated_due_date_str = request.form['due_date']

        # Convert the updated_due_date to a date object
        updated_due_date = datetime.strptime(updated_due_date_str, "%Y-%m-%d").date()

        # Update the item in the database
        item.todo = updated_todo
        item.due_date = updated_due_date

        db.session.commit()  # Commit the changes to the database

        # Redirect to the home page or some other page
        return redirect(url_for('home'))

    # If it's a GET request, show the form pre-filled with current values
    return render_template('edit.html', item=item)

@app.route("/deleted_items")
@login_required
@admin_only  # Ensure only admin can view this page
def deleted_items():
    # Fetch deleted items
    deleted_result = db.session.execute(db.select(Item).filter(Item.deleted_at.is_not(None)))  # Get deleted items
    deleted_todo_list = deleted_result.scalars().all()

    return render_template("deleted_items.html", current_user=current_user, deleted_todo_list=deleted_todo_list)

# Restores the deleted items
@app.route("/restore_item/<int:item_id>")
@login_required
@admin_only  # Only admins can restore items
def restore_item(item_id):
    item = Item.query.get_or_404(item_id)
    item.deleted_at = None  # Mark as not deleted
    db.session.commit()
    flash("Item restored successfully.") # When the user clicks 'Restore' the flash message should render on screen, see deleted_items.html

    return redirect(url_for("deleted_items")) # Redirect to deleted items page after restore

@app.route('/completed_items')
@login_required
def completed_items():
    # Fetch the completed items (adjust according to your database model)
    _completed_items = Item.query.filter_by(completed=True, owner_id=current_user.id).all()

    return render_template('completed_items.html', completed_todo_list=_completed_items)

# Restores the completed items
@app.route('/restore_completed_item/<int:item_id>', methods=['GET', 'POST'])
@login_required
def restore_completed_item(item_id):
    # Fetch the item from the database using the item_id
    item = Item.query.get_or_404(item_id)

    # Update the item status to not completed
    item.completed = False

    try:
        db.session.commit()
        flash('Item has been restored successfully!')
    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred while restoring the item: {str(e)}")

    return redirect(url_for('completed_items'))

if __name__ == '__main__':
    app.run(debug=True)