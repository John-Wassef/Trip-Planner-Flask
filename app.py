from flask import Flask, request, jsonify
from flask_restx import Api, fields, Resource
from flask_cors import CORS
from geopy.distance import geodesic
from collections import namedtuple
import requests
import heapq

app = Flask(__name__)
CORS(app)
api = Api(app, version='1.0', title='Museum Trip Planner API',
          description='API to plan a trip to museums in various cities')

# Customize Swagger UI to remove 'X-Field'
app.config['SWAGGER_UI_DOC_EXPANSION'] = 'none'
app.config['RESTX_MASK_SWAGGER'] = False  # This removes the 'X-Field'

# Define a named tuple for points
Point = namedtuple('Point', ['latitude', 'longitude'])

# Define the input model for the POST request
trip_input = api.model('TripInput', {
    'cities': fields.List(fields.String, required=True, description='List of cities to fetch museums from'),
    'start_location': fields.String(required=True,
                                    description="Start location (either 'current location' or a museum name/index)")
})

# Define the input model for showing museums in cities
show_museums_input = api.model('ShowMuseumsInput', {
    'cities': fields.List(fields.String, required=True, description='List of cities to fetch museums from')
})

# Define the output model for the response
museum_output = api.model('Museum', {
    'name': fields.String(required=True, description='Museum name'),
    'latitude': fields.Float(required=True, description='Latitude'),
    'longitude': fields.Float(required=True, description='Longitude'),
    'city': fields.String(required=True, description='City'),
    'imageUrl': fields.String(description='Image link')
})

# Define the output model for the trip planner response, which includes distance
museum_with_distance_output = api.model('MuseumWithDistance', {
    'name': fields.String(required=True, description='Museum name'),
    'latitude': fields.Float(required=True, description='Latitude'),
    'longitude': fields.Float(required=True, description='Longitude'),
    'city': fields.String(required=True, description='City'),
    'imageUrl': fields.String(description='Image link'),
    'distance': fields.Float(description='Distance from start location in kilometers')
})

trip_output = api.model('TripOutput', {
    'trip_plan': fields.List(fields.Nested(museum_with_distance_output), required=True,
                             description='Planned trip to museums')
})


def get_current_location():
    try:
        # Using an IP-based service to get location
        response = requests.get('https://ipinfo.io')
        data = response.json()
        print(f"IPInfo Response: {data}")  # Debugging line
        if 'loc' in data:
            latitude, longitude = data['loc'].split(',')
            print(f"Current Location Latitude: {latitude}, Longitude: {longitude}")  # Debugging line
            return float(latitude), float(longitude)
        else:
            raise ValueError("Location data not found in IPInfo response")
    except Exception as e:
        print(f"Error retrieving current location: {e}")
        return None, None


def fetch_museum_data(city_name):
    url = f"https://historyproject.somee.com/api/Museums/city/{city_name}"
    response = requests.get(url)
    if response.status_code == 200:
        museum_data = response.json()
        cleaned_museum_data = [{key: value for key, value in museum.items() if key != 'id'} for museum in museum_data]
        return {"city": city_name, "data": cleaned_museum_data}
    else:
        print(f"Error fetching museum data for '{city_name}': {response.status_code}")
        return None


def calculate_distance(point1, point2):
    print(f"Calculating distance from {point1} to {point2}")  # Debugging line
    distance = geodesic((point1.latitude, point1.longitude), (point2.latitude, point2.longitude)).kilometers
    print(f"Calculated Distance: {distance} km")  # Debugging line
    return distance


def fetch_museums_for_cities(cities):
    all_museums = []
    for city in cities:
        museums_dict = fetch_museum_data(city)
        if museums_dict and 'data' in museums_dict:
            for museum in museums_dict['data']:
                museum['city'] = city
            all_museums.extend(museums_dict['data'])
        else:
            print(f"No museum data found for '{city}'.")
    return all_museums


def heuristic(a, b):
    return geodesic((a.latitude, a.longitude), (b.latitude, b.longitude)).kilometers


def a_star_search(start, museums):
    visited = set()
    trip_plan = []
    current_location = start

    while museums:
        closest_museum = min(museums, key=lambda museum: heuristic(current_location, Point(museum['latitude'], museum['longitude'])))
        closest_museum['distance'] = heuristic(current_location, Point(closest_museum['latitude'], closest_museum['longitude']))
        trip_plan.append(closest_museum)
        current_location = Point(closest_museum['latitude'], closest_museum['longitude'])
        museums.remove(closest_museum)

    return trip_plan


@api.route('/plan_trip')
class PlanTrip(Resource):
    @api.expect(trip_input)
    @api.marshal_with(trip_output)
    def post(self):
        input_data = request.json
        cities = input_data['cities']
        start_location_input = input_data['start_location']

        museums = fetch_museums_for_cities(cities)
        if not museums:
            return {'error': "No valid museums found for the provided cities. Please enter valid city names."}, 400

        start_location = None
        if start_location_input.lower() == "current location":
            latitude, longitude = get_current_location()
            if latitude is None or longitude is None:
                return {'error': "Unable to fetch current location."}, 400
            start_location = Point(latitude=latitude, longitude=longitude)
        else:
            chosen_museum = next(
                (museum for museum in museums if start_location_input.lower() == museum['name'].lower()), None)
            if chosen_museum:
                start_location = Point(latitude=chosen_museum['latitude'], longitude=chosen_museum['longitude'])
            else:
                try:
                    start_location_index = int(start_location_input) - 1
                    if 0 <= start_location_index < len(museums):
                        chosen_museum = museums[start_location_index]
                        start_location = Point(latitude=chosen_museum['latitude'], longitude=chosen_museum['longitude'])
                    else:
                        return {
                            'error': "Invalid start location number. Please enter a valid number or museum name."}, 400
                except ValueError:
                    return {'error': "Invalid start location input. Please enter a valid number or museum name."}, 400

        if not start_location:
            return {'error': "Could not determine start location. Please try again."}, 400

        start_museum = Point(start_location.latitude, start_location.longitude)

        # Run the A* algorithm
        trip_plan = a_star_search(start_museum, museums)

        return {'trip_plan': trip_plan}


@api.route('/show_museums')
class ShowMuseums(Resource):
    @api.expect(show_museums_input)
    @api.marshal_with(museum_output, as_list=True)
    def post(self):
        input_data = request.json
        cities = input_data['cities']

        museums = fetch_museums_for_cities(cities)
        if not museums:
            return {'error': "No valid museums found for the provided cities. Please enter valid city names."}, 400

        return museums


# Only include this block if you want to run this script directly for development
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
