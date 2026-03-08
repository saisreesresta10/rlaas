"""Main application entry point for RLaaS"""

import asyncio
import uvicorn
from .config import get_config
from .logging_service import get_structured_logger, configure_structured_logging


def main():
    """Main entry point for RLaaS application"""
    # Configure structured logging first
    configure_structured_logging()
    
    # Get logger
    structured_logger = get_structured_logger()
    
    try:
        # Load configuration
        config = get_config()
        
        # Log application startup
        structured_logger.log_startup_event(
            startup_event="application_start",
            component="main",
            success=True,
            details={
                "host": config.server.host,
                "port": config.server.port,
                "workers": config.server.workers,
                "log_level": config.server.log_level.value
            }
        )
        
        # Start the server
        uvicorn.run(
            "rlaas.api:app",
            host=config.server.host,
            port=config.server.port,
            workers=config.server.workers,
            reload=config.server.reload,
            log_level=config.server.log_level.value.lower(),
            access_log=True
        )
        
    except Exception as e:
        # Log startup failure
        structured_logger.log_startup_event(
            startup_event="application_start_failed",
            component="main",
            success=False,
            details={"error": str(e)}
        )
        
        structured_logger.log_error(
            error_type="startup_error",
            component="main",
            message=f"Failed to start RLaaS application: {str(e)}"
        )
        
        raise


if __name__ == "__main__":
    main()