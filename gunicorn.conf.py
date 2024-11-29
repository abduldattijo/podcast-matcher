import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"
backlog = 32

workers = 1  # Reduce to 1 for Render free tier
worker_class = 'sync'
worker_connections = 50
timeout = 120  # Increased timeout
keepalive = 2

proc_name = 'podcast-matcher'

accesslog = '-'
errorlog = '-'
loglevel = 'info'

daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

max_requests = 50  # Reduced
max_requests_jitter = 5
reload = False
spew = False

# Worker lifecycle hooks
def post_fork(server, worker):
    server.log.info("Worker spawned (pid: %s)", worker.pid)

def pre_fork(server, worker):
    pass

def pre_exec(server):
    server.log.info("Forked child, re-executing.")

def when_ready(server):
    server.log.info("Server is ready. Spawning workers")

def worker_int(worker):
    worker.log.info("worker received INT or QUIT signal")

def worker_abort(worker):
    worker.log.info("worker received SIGABRT signal")

# Resource limits
worker_term_timeout = 30
graceful_timeout = 30
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190