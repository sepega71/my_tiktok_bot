import subprocess
import sys

# Запускаем бота с перенаправлением вывода в файл
with open('bot_output.log', 'w', encoding='utf-8') as log_file:
    process = subprocess.Popen(
        [sys.executable, 'bot.py'],
        stdout=log_file,
        stderr=log_file,
        universal_newlines=True,
        bufsize=1
    )
    
    # Ждем завершения процесса (или вручную остановим)
    print(f"Бот запущен с PID {process.pid}. Логи записываются в bot_output.log")
    print("Для остановки нажмите Ctrl+C")
    
    try:
        process.wait()
    except KeyboardInterrupt:
        print("\nОстанавливаем бота...")
        process.terminate()
        process.wait()
        print("Бот остановлен.")