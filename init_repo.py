import os
import sys

def init_git_repo():
    """Сообщает, что репозиторий уже инициализирован."""
    print("Репозиторий уже инициализирован. Git-операции не требуются при деплое на Render.com.")

if __name__ == "__main__":
    init_git_repo()