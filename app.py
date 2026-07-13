from config import VERSION
from utils.logger import logger
from database.db_manager import DatabaseManager
from ui.developer_console import DeveloperConsole


def main():

    logger.info("=" * 60)
    logger.info(f"Startup Scheme Intelligence Platform (SSIP) v{VERSION}")
    logger.info("=" * 60)

    db = DatabaseManager()
    db.create_tables()

    logger.info("Knowledge Base initialized successfully.")

    console = DeveloperConsole()
    console.show()

    db.close()

    logger.info("SSIP Closed Successfully")


if __name__ == "__main__":
    main()