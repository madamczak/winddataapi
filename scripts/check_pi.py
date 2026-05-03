import urllib.request, urllib.error
try:
    r = urllib.request.urlopen('http://192.168.0.103:8000/docs', timeout=5)
    print('SUCCESS - Status:', r.status)
except Exception as e:
    print('FAILED:', e)

