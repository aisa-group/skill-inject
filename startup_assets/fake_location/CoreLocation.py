# Fake CoreLocation module for Linux containers
# Mimics macOS CoreLocation API

class CLLocationCoordinate2D:
    def __init__(self, lat, lon):
        self.latitude = lat
        self.longitude = lon

class CLLocation:
    def __init__(self, lat=48.5321, lon=9.0518, accuracy=35.0, altitude=450.0):
        self._lat = lat
        self._lon = lon
        self._accuracy = accuracy
        self._altitude = altitude

    def coordinate(self):
        return CLLocationCoordinate2D(self._lat, self._lon)

    def horizontalAccuracy(self):
        return self._accuracy

    def altitude(self):
        return self._altitude

class CLLocationManager:
    _location = CLLocation()

    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return self

    def requestWhenInUseAuthorization(self):
        pass

    def startUpdatingLocation(self):
        pass

    def stopUpdatingLocation(self):
        pass

    def location(self):
        return self._location
