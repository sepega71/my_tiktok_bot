import os
import subprocess
import sys

def init_git_repo():
    """Инициализирует git-репозиторий и делает первый коммит."""
    try:
        # Проверяем, существует ли уже .git
        if os.path.exists('.git'):
            print("Репозиторий уже инициализирован.")
        else:
            # Инициализируем репозиторий
            subprocess.run(['git', 'init'], check=True)
            print("Репозиторий инициализирован.")

        # Добавляем все файлы
        subprocess.run(['git', 'add', '.'], check=True)
        print("Файлы добавлены.")

        # Делаем первый коммит
        subprocess.run(['git', 'commit', '-m', 'Initial commit'], check=True)
        print("Первый коммит создан.")
    except subprocess.CalledProcessError as e:
        print(f"Ошибка при работе с Git: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print("Git не найден. Убедитесь, что Git установлен и добавлен в PATH.")
        sys.exit(1)

if __name__ == "__main__":
    init_git_repo()