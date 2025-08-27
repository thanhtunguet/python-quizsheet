#!/usr/bin/env python3
"""
Health check script for the quiz processor API.
Can be used for Docker health checks or monitoring.
"""

import sys
import httpx
import asyncio

async def health_check(host="localhost", port=8000, timeout=10):
    """
    Perform a health check on the quiz processor API.
    
    Args:
        host: API host (default: localhost)
        port: API port (default: 8000)
        timeout: Request timeout in seconds (default: 10)
    
    Returns:
        bool: True if healthy, False otherwise
    """
    try:
        url = f"http://{host}:{port}/"
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("ok") is True:
                    print("✅ Health check passed")
                    return True
                else:
                    print("❌ Health check failed: Invalid response format")
                    return False
            else:
                print(f"❌ Health check failed: HTTP {response.status_code}")
                return False
                
    except httpx.TimeoutException:
        print(f"❌ Health check failed: Timeout after {timeout}s")
        return False
    except httpx.ConnectError:
        print(f"❌ Health check failed: Cannot connect to {host}:{port}")
        return False
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False

def main():
    """Main function for command line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Health check for quiz processor API")
    parser.add_argument("--host", default="localhost", help="API host (default: localhost)")
    parser.add_argument("--port", type=int, default=8000, help="API port (default: 8000)")
    parser.add_argument("--timeout", type=int, default=10, help="Timeout in seconds (default: 10)")
    
    args = parser.parse_args()
    
    # Run the health check
    is_healthy = asyncio.run(health_check(args.host, args.port, args.timeout))
    
    # Exit with appropriate code
    sys.exit(0 if is_healthy else 1)

if __name__ == "__main__":
    main()
