import asyncio
from healthcheck import health_check

# Test health check function exists and is callable
assert callable(health_check), 'health_check should be callable'
print('✅ Health check script test passed')
