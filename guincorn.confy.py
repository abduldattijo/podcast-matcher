import multiprocessing
import os

# Server socket
bind = f"0.0.0.0:{os.getenv('PORT', '8080')}"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = 'gthread'
threads = 4
worker_connections = 1000
timeout = 300
keepalive = 65
max_requests = 1000
max_requests_jitter = 50

# Process naming
proc_name = 'podcast-matcher'
pylint = False

# Logging
errorlog = '-'
loglevel = 'info'
accesslog = '-'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Server mechanics
daemon = False
raw_env = [
    f"APP_ENV={os.getenv('APP_ENV', 'production')}",
]

# SSL
keyfile = None
certfile = None

# Process management
preload_app = False
reload = False
reload_engine = 'auto'

def when_ready(server):
    server.log.info("Server is ready.")

def on_starting(server):
    server.log.info("Server is starting.")

def on_exit(server):
    server.log.info("Server is shutting down.")