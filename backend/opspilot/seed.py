from .config import Settings
from .storage import Store


def main() -> None:
    store = Store(Settings().db_path)
    store.initialize()
    store.seed()
    print(f"Seeded local demo data in {store.path}")


if __name__ == "__main__":
    main()
