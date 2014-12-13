from flask import render_template, request, jsonify, g, redirect, flash, url_for
from flask import session as flask_session
from model import Bike, Listing, User, Favorite
import model
from app import app, db, facebook, bikeindex
import datetime
import json
import requests
import os

@facebook.tokengetter
def get_facebook_token():
    return flask_session.get('facebook_token')

@app.route("/facebook_login")
def facebook_login():
    return facebook.authorize(callback=url_for('facebook_authorized',
        next=request.args.get('next'), _external=True))

@app.route("/facebook_authorized")
@facebook.authorized_handler
def facebook_authorized(resp):
    if resp is None or 'access_token' not in resp:
    	flash("Facebook authentication error.")
        return redirect('/login')
    else:
    	flask_session['logged_in'] = True
    	flask_session['facebook_token'] = (resp['access_token'], '')

    	user = add_new_user()

    	flask_session['user'] = user.id 

    	flash("You are logged in.")
    	return redirect(url_for('index')) # How to detect which page they were headed for?

def add_new_user():
	""" Uses FB id to check for exisiting user in db. If none, adds new user."""
	fb_user = facebook.get('/me').data
	existing_user = db.session.query(User).filter(User.facebook_id == fb_user['id']).first()
	if existing_user is None:
		new_user = model.User()
		new_user.facebook_id = fb_user['id']
		new_user.first_name = fb_user['first_name']
		new_user.last_name = fb_user['last_name']
		new_user.email = fb_user['email']
		new_user.facebook_url = fb_user['link']
		new_user.avatar = get_user_photo()
		# commit new user to database
		db.session.add(new_user)
		db.session.commit()
		# Go get that new user
		new_user = db.session.query(User).filter(User.facebook_id == fb_user['id']).first()
		return new_user
	else:
		return existing_user

def get_user_photo():
	photo = facebook.get('/me/picture?redirect=0&height=1000&type=normal&width=1000').data
	photo_url = photo['data']['url']
	return photo_url

@app.route("/logout")
def logout():
    clear_session()
    flash("Successfully logged out.")
    return redirect('/')

@app.route('/clearsession')
def clear_session():
	flask_session['logged_in'] = None
	flask_session['facebook_token'] = None
	flask_session['BI_authorized'] = None
	flask_session['bikeindex_token'] = None
	flask_session['user'] = None
	return "Session cleared!"

@app.route('/getsession')
def get_session():
	print "\nLogged in:", flask_session.get('logged_in', 'Not set')
	print "\n Facebook token:", flask_session.get('facebook_token','Not set')
	print "\n BikeIndex authorized:", flask_session.get('BI_authorized', 'Not set')
	print "\n BikeIndex token:", flask_session.get('bikeindex_token', 'Not set')
	print "\n Current user:", flask_session.get("user", "Not set")

# Bike Index OAuth:

@bikeindex.tokengetter # ???
def get_bikeindex_token():
    return flask_session.get('bikeindex_token')

@app.route("/bikeindex_login") # ???
def bikeindex_login():
    return bikeindex.authorize(callback=url_for('bikeindex_authorized', _external=True))

@app.route("/bikeindex_authorized", methods=['GET','POST']) # Not working
@bikeindex.authorized_handler
def bikeindex_authorized(resp):
	""" Running into issues here with BikeIndex OAuth (Key error]"""
	print "\n\n\n response from bikeindex", resp
	flask_session['BI_authorized'] = True
	flask_session['bikeindex_token'] = resp['code']

@app.route("/getuser_bikeindex") # This works with hard-coded access token
def user_data():
    """Grab user profile information from Bike Index."""
    access_token = os.environ.get('BIKEINDEX_ACCESS_TOKEN')
    # access_token = flask_session['bikeindex_token']
    BI_request = requests.get('https://bikeindex.org/api/v2/users/current?access_token=' + access_token)
    BI_user = BI_request.json()	 
    bikeindex_userdata = {
         	'bikeindex_user_id': BI_user['id'],
            'bike_ids': BI_user['bike_ids']
         }
    # Will put something here that stores user's bike ids in database
    return jsonify(bikeindex_userdata)

# function to write if i get bikeindex oauth to work
def add_user_bikes(user):
	pass

# Runs on browser refresh to make user available on templates.
@app.before_request
def set_current_user():
    current_user = flask_session.get('user', None)
    if current_user:
    	user = db.session.query(User).filter_by(id=current_user).one()
    	g.user = user.id
    	g.avatar = user.avatar
    	g.name = user.first_name
    	g.logged_in = True
    # pass

# makes user available to javascript
@app.route("/getuser")
def get_current_user():
    try:
        return jsonify({"user": g.user, "avatar": g.avatar, "name": g.name, "favorites": get_favorites() })
    except AttributeError:
        return jsonify({"user": None})

@app.route("/")
def index():
	# home route renders template and all content is generated by javascript
	return render_template("index.html")

@app.route("/getbikes")
def get_bikes():
	""" get search results """
	# Get user-submitted filters from form
	print "get bikes called!"

	sizes = request.args.getlist('sizes[]') 		
	materials = request.args.getlist('materials[]') 		
	handlebars = request.args.getlist('handlebars[]') 		
	min_price = request.args.get('minPrice')
	max_price = request.args.get('maxPrice')

	lat_min = request.args.get('latitudeMin')
	lat_max = request.args.get('latitudeMax')
	long_min = request.args.get('longitudeMin')
	long_max = request.args.get('longitudeMax')

	# Base query for active listings
	query = db.session.query(Listing, Bike).filter(Listing.bike_id == Bike.id, Listing.post_status=="Active") 
	# print query
	# query = Listing.query.join(Bike).filter(Listing.bike_id == Bike.id, Listing.post_status=="Active")

	# Filter for listings within current map view
	try:
		query = query.filter(Listing.latitude > float(lat_min)).filter(Listing.latitude < float(lat_max))
		query = query.filter(Listing.longitude > float(long_min)).filter(Listing.longitude < float(long_max))
	except ValueError:
		pass
	except TypeError:
		pass

	# Filters from form
	if sizes:
		query = query.filter(Bike.size_category.in_(sizes))
	if materials:	
		query = query.filter(Bike.frame_material.in_(materials))
	if handlebars:
		query = query.filter(Bike.handlebar_type.in_(handlebars))
	if min_price:
		query = query.filter(Listing.asking_price >= float(min_price.replace(',','')))
	if max_price:
		query = query.filter(Listing.asking_price <= float(max_price.replace(',','')))

	# Get total number of listings found for this search before applying page limit
	total_count = query.count()

	# Find out which page is being requested
	current_page = int(request.args.get("currentPage"))

	# Number of results per page
	limit = int(request.args.get("resultLimit"))

	# Default order by ascending price 
	query = query.order_by(Listing.asking_price.asc())

	# Apply the offset depending on the page number and results/page
	offset = current_page * limit

	query = query.offset(offset)

	# Finish the query
	all_listings = query.limit(limit)	

	# Initializing response object
	response = {
		"listings": [],
		"num_results": int(all_listings.count()),
		"page_range_lower": None,
		"page_range_upper": None,
		"total_results": int(total_count),
	}

	# Building final response object
	for listing, bike in all_listings:
		response["listings"].append({
						'url': "/listing/" + str(bike.id),
						'latitude': listing.latitude, 
						'longitude': listing.longitude,
						'id': listing.id,
						'photo': bike.photo,
						'price': listing.asking_price,
						'material': bike.frame_material,
						'title': bike.title })
		if current_page == 0:
			response["page_range_lower"] = 1
		else:
			response["page_range_lower"] = offset + 1
		response["page_range_upper"] = response["page_range_lower"] + response["num_results"] - 1
	print "Response object for javascript", response
	return jsonify(response=response)

@app.route("/fetchbike")
def fetch_bike():
	""" Fetches bike from BikeIndex API by serial number"""
	serial = request.args.get("serial")
	r = requests.get("https://bikeindex.org/api/v1/bikes?serial=" + serial)
	bike = r.json()
	return jsonify(response=bike)

@app.route("/addbike", methods=['POST'])
def add_bike():
	""" Takes bike object from BikeIndex API and adds bike info to db"""

	bike_JSON= request.form.get("bike")	# Get JSON bike object from ajax ({bike: bikedata})
	bike = json.loads(bike_JSON)	# JSON string --> Python dictionary

	if bike["stolen"]:
		return "Stolen bike! Do not add."

	# Create new bike instance for bike table
	new_bike = Bike()

	# Populate bike attributes
	new_bike.id = bike["id"]	
	new_bike.user_id = g.user
	new_bike.serial = bike["serial"]	
	new_bike.size = bike["frame_size"]
	new_bike.manufacturer = bike["manufacturer_name"]
	new_bike.rear_tire_narrow = bike["rear_tire_narrow"] 
	new_bike.type_of_cycle = bike["type_of_cycle"]
	new_bike.bikeindex_url = bike["url"]
	new_bike.photo = bike["photo"]
	new_bike.thumb = bike["thumb"]
	new_bike.title = bike["manufacturer_name"] + " " + bike["frame_model"]
	new_bike.frame_model = bike["frame_model"]
	new_bike.year = bike["year"]
	new_bike.paint_description = bike["paint_description"] 
	new_bike.front_tire_narrow = bike["front_tire_narrow"]

	# list of valid size categories 
	valid_sizes = ['xs','s','m','l','xl']

	# normalizing frame size measurements 
	if len(new_bike.size) > 0 and new_bike.size not in valid_sizes:
		if new_bike.size.endswith('in'):
			# converting inches to centimeters
			size_convert = float(new_bike.size[:-2]) * 2.54
		elif new_bike.size.endswith('cm'):
			# floating the cm
			size_convert = float(new_bike.size[:-2])
	else:
		size_convert = "no need to convert"
		new_bike.size_category = new_bike.size

	# putting sizes into categories
	if type(size_convert) is float:
		if size_convert < 50:
			new_bike.size_category = "xs"
		elif size_convert >= 50 and size_convert <= 53:
			new_bike.size_category = "s"
		elif size_convert > 53 and size_convert <= 56:
			new_bike.size_category = "m"
		elif size_convert > 56 and size_convert <= 59:
			new_bike.size_category = "l"
		elif size_convert > 59:
			new_bike.size_category = "xl"

	# changing size abbrevation for display
	size_to_display = {"xs": "Extra Small", "s":"Small", "m":"Medium", "l":"Large", "xl": "Extra Lsarge" }
	if new_bike.size in valid_sizes:
		new_bike.size = size_to_display[new_bike.size]

	# breaking frame colors out of list format
	new_bike.frame_colors = "" 		
	for color in bike["frame_colors"]:
		new_bike.frame_colors += color

	if bike["handlebar_type"] != None:
		new_bike.handlebar_type = bike["handlebar_type"].get("name", None)
	
	if bike["frame_material"] != None:
		new_bike.frame_material = bike["frame_material"].get("name", None)

	if bike["rear_wheel_size"] != None:
		new_bike.rear_wheel_size = bike["rear_wheel_size"].get("name", None)
		new_bike.rear_wheel_size_iso_bsd = bike["rear_wheel_size"].get("iso_bsd", None) 
	
	if bike["front_wheel_size"] != None:
		new_bike.front_wheel_size = bike["front_wheel_size"].get("name", None)	
		new_bike.front_wheel_size_iso_bsd = bike["front_wheel_size"].get("iso_bsd", None)	
	
	if bike["front_gear_type"] != None:
		new_bike.front_gear_type = bike["front_gear_type"].get("name", None) 
	
	if bike["rear_gear_type"] != None:
		new_bike.rear_gear_type = bike["rear_gear_type"].get("name", None)

	# Add bike to session and commit changes
	db.session.add(new_bike)
	db.session.commit() 

	# Store bike id in flask session (to remember it for listing)
	flask_session["bike"] = bike["id"]

	return "Added bike to database"

@app.route("/list")
def listing_form():
	bike_id = flask_session.get("bike")
	bike = db.session.query(Bike).get(bike_id)
	return render_template("listing_form.html", bike=bike)

@app.route("/addlisting", methods=['POST'])
def add_listing():
	
	new_listing = Listing()

	new_listing.bike_id = flask_session["bike"]	# get bike id from flask session
	new_listing.post_date = datetime.datetime.now()
	new_listing.post_expiration = datetime.datetime.now() + datetime.timedelta(30) # Post expires 30 days from now
	new_listing.post_status = "Active"
	new_listing.asking_price = request.form["price"] # FORM
	new_listing.latitude = request.form["latitude"] # FORM
	new_listing.longitude = request.form["longitude"] # FORM
	new_listing.additional_text = request.form["comments"] #FORM
	new_listing.user_id = g.user # Flask session
	new_listing.email = request.form["email"] #FORM

	db.session.add(new_listing)
	db.session.commit()

	return str(new_listing.bike_id)

@app.route("/deletelisting", methods=['POST'])
def delete_listing():
	listing_id = request.form.get("listingId");

	listing_to_delete = db.session.query(Listing).get(listing_id)
	db.session.delete(listing_to_delete)

	bike_to_delete = db.session.query(Bike).get(listing_to_delete.bike_id)
	db.session.delete(bike_to_delete)

	favorites = db.session.query(Favorite).filter_by(listing_id=listing_id).all()
	for favorite in favorites:
		favorite_to_delete = db.session.query(Favorite).get(favorite.id)
		db.session.delete(favorite_to_delete)

	db.session.commit()

	# To figure out: How should post functions return a status response?
	return "listing deleted"

@app.route("/seebike/<int:id>")
def see_bike(id):
	bike = db.session.query(Bike).get(id)
	return bike.title

@app.route("/listing/<int:bike_id>") 
def listing_success(bike_id):
	# Use bike_id to get listing
	listing = db.session.query(Listing).filter(Listing.bike_id == bike_id, Listing.post_status=="Active").one()
	# Get user from listing
	user = db.session.query(User).filter_by(id=listing.user_id).first()
	# Use bike_id to get bike
	bike = db.session.query(Bike).get(bike_id)
	return render_template("listing.html", bike=bike, user=user, listing=listing)

@app.route("/mylistings")
def my_listings():
	user = flask_session['user']
	query = db.session.query(Listing, Bike).filter(Listing.bike_id == Bike.id, Listing.post_status=="Active")
	user_listings = query.filter(Listing.user_id == user).filter(Bike.user_id == user).all()

	listings = []

	# Building objects for template
	for listing, bike in user_listings:
		listings.append({'id': listing.id,
						'url': "/listing/" + str(bike.id),
						 'photo': bike.photo,
						 'price': listing.asking_price,
						 'title': bike.title,
						 'date': listing.post_date})

	return render_template('mylistings.html', listings=listings)

@app.route("/favoritebikes")
def user_favorites():

	favorites = get_favorites()
	listings = []

	if favorites != None:
		for listing_id in favorites:
			listing_bike = [db.session.query(Listing, Bike).filter(Listing.bike_id == Bike.id, Listing.id == listing_id).first()]
			for listing, bike in listing_bike:
				listings.append({'url': "/listing/" + str(bike.id),
								 'photo': bike.photo,
								 'price': listing.asking_price,
								 'title': bike.title,
								 'date': listing.post_date,
								 'id': listing.id})
	return render_template('myfavoritebikes.html', listings=listings)

@app.route("/favorite", methods=["POST"])
def add_or_remove_favorite():
	listing_id = request.form.get("listing")
	user_id = flask_session["user"]

	# check if user has already favorited that listing
	existing_fav = db.session.query(Favorite).filter(Favorite.user_id == user_id).filter(Favorite.listing_id == listing_id).first()

	if existing_fav != None:
		db.session.delete(existing_fav)
	else:
		new_favorite = Favorite()
		new_favorite.user_id = user_id
		new_favorite.listing_id = listing_id
		db.session.add(new_favorite)
	
	db.session.commit()
	return "favorite added or removed"

def get_favorites():
	""" get list of ids of current user's favorited bikes """
	user_id = flask_session.get('user', None)
	favorites = []

	if user_id != None:
		query_favorites = db.session.query(Favorite).filter(Favorite.user_id == user_id).all()
		for favorite in query_favorites:
			favorites.append(favorite.listing_id)
	if len(favorites) > 0:
		return favorites
	else:
		return None

