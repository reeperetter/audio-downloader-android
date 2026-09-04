import asyncio
import os
import re
import tempfile
import flet as ft
# yt_dlp навмисно НЕ імпортується тут: на Android збірка може не мати
# сумісних колес для деяких його C-залежностей (brotli, pycryptodomex тощо).
# Якщо імпорт впаде тут, на верхньому рівні модуля, застосунок помре ще
# до створення першого віджета -> білий екран без жодного повідомлення.
# Тому імпортуємо лениво, всередині функцій, де вже є try/except.


def format_duration(seconds):
    if seconds is None:
        return "[LIVE]"
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "--:--"

    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"[{hours}:{minutes:02d}:{seconds:02d}]"
    return f"[{minutes:02d}:{seconds:02d}]"


def clean_title(title):
    if not title:
        return "Невідома назва"
    return re.sub(r"\s+", " ", title).strip()


def get_default_download_dir():
    """
    Шукаємо реальну публічну папку "Завантаження" на Android.
    Якщо немає прав/доступу - надійно падаємо в папку самого застосунку
    (вона завжди доступна для запису без жодних дозволів).
    Раніше тут був шлях "~/Storage/Downloads" - це шлях з Termux,
    якого на звичайному Android без Termux просто не існує, тому файли
    мовчки летіли у тимчасову системну папку.
    """
    android_downloads = "/storage/emulated/0/Download"
    try:
        if os.path.isdir(android_downloads) and os.access(android_downloads, os.W_OK):
            return android_downloads
    except Exception:
        pass

    app_storage = os.getenv("FLET_APP_STORAGE_DATA")
    if app_storage:
        music_dir = os.path.join(app_storage, "Music")
        try:
            os.makedirs(music_dir, exist_ok=True)
            return music_dir
        except Exception:
            pass

    return tempfile.gettempdir()


async def main(page: ft.Page):
    # Захист від білого екрану: глобальний відлов помилок UI
    try:
        page.title = "Music Downloader"
        page.theme_mode = ft.ThemeMode.LIGHT
        page.padding = 10

        page.window_width = 780
        page.window_height = 680

        default_dir = get_default_download_dir()

        selected_folder = default_dir
        search_results_data = []
        current_audio = None

        async def stop_current_audio():
            nonlocal current_audio
            if current_audio:
                try:
                    current_audio.pause()
                except Exception:
                    pass
                if current_audio in page.overlay:
                    page.overlay.remove(current_audio)
                current_audio = None
                await page.update_async()

        search_input = ft.TextField(
            hint_text="Пошук музики...",
            expand=True,
        )

        limit_combo = ft.Dropdown(
            options=[
                ft.dropdown.Option("10"),
                ft.dropdown.Option("15"),
                ft.dropdown.Option("20"),
            ],
            value="10",
            width=75,
        )

        search_button = ft.ElevatedButton("Шукати")
        results_list = ft.ListView(expand=True, spacing=5, padding=5)

        select_all_btn = ft.OutlinedButton("Все")
        clear_btn = ft.OutlinedButton("Скинути")
        download_btn = ft.ElevatedButton("Завантажити", disabled=True)

        folder_input = ft.TextField(
            value=selected_folder, read_only=True, expand=True
        )
        folder_button = ft.ElevatedButton("Огляд")

        status_label = ft.Text("Готовий до роботи")
        progress_bar = ft.ProgressBar(value=0, visible=True)

        async def on_folder_result(e: ft.FilePickerResultEvent):
            nonlocal selected_folder
            if e.path:
                selected_folder = e.path
                folder_input.value = e.path
                await page.update_async()

        file_picker = ft.FilePicker(on_result=on_folder_result)
        page.overlay.append(file_picker)

        folder_button.on_click = lambda _: file_picker.get_directory_path(
            dialog_title="Оберіть папку збереження"
        )

        async def set_busy(busy: bool):
            search_input.disabled = busy
            limit_combo.disabled = busy
            search_button.disabled = busy
            select_all_btn.disabled = busy
            clear_btn.disabled = busy
            download_btn.disabled = busy
            folder_button.disabled = busy
            await page.update_async()

        async def play_audio_preview(url: str, play_btn: ft.IconButton):
            nonlocal current_audio
            await stop_current_audio()

            play_btn.icon = ft.icons.HOURGLASS_EMPTY
            await page.update_async()

            loop = asyncio.get_running_loop()
            tmp_dir = tempfile.mkdtemp(prefix="preview_")

            def _download_preview():
                import yt_dlp  # лінивий імпорт, помилка потрапить у except нижче
                # Завантажуємо короткий локальний файл прев'ю замість прямого
                # стрімінгу: пряме посилання YouTube часто вимагає спеціальних
                # заголовків (headers/Referer), які плеєр Flet передати не може,
                # тому пряме відтворення URL нерідко падає з мережевою помилкою.
                ydl_opts = {
                    "format": "bestaudio[ext=m4a]/bestaudio/best",
                    "outtmpl": os.path.join(tmp_dir, "preview.%(ext)s"),
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return ydl.prepare_filename(info)

            try:
                local_path = await loop.run_in_executor(None, _download_preview)
                if local_path and os.path.exists(local_path):
                    audio = ft.Audio(src=local_path, autoplay=True)
                    current_audio = audio
                    page.overlay.append(audio)
                    play_btn.icon = ft.icons.STOP
                    await page.update_async()
                else:
                    play_btn.icon = ft.icons.PLAY_ARROW
                    page.snack_bar = ft.SnackBar(ft.Text("Не вдалося отримати аудіо для прослуховування."))
                    page.snack_bar.open = True
                    await page.update_async()
            except Exception as exc:
                play_btn.icon = ft.icons.PLAY_ARROW
                page.snack_bar = ft.SnackBar(ft.Text(f"Помилка відтворення: {exc}"))
                page.snack_bar.open = True
                await page.update_async()

        async def start_search(e):
            await stop_current_audio()
            query = search_input.value.strip()
            if not query:
                page.snack_bar = ft.SnackBar(ft.Text("Введіть назву треку!"))
                page.snack_bar.open = True
                await page.update_async()
                return

            await set_busy(True)
            results_list.controls.clear()
            search_results_data.clear()
            progress_bar.value = None
            status_label.value = f"Пошук: {query}..."
            await page.update_async()

            limit = int(limit_combo.value)
            loop = asyncio.get_running_loop()

            def _search_sync():
                import yt_dlp  # лінивий імпорт, помилка потрапить у except нижче
                search_query = f"ytsearch{limit}:{query} audio"
                ydl_opts = {
                    "extract_flat": True,
                    "skip_download": True,
                    "quiet": True,
                    "no_warnings": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(search_query, download=False)

            try:
                data = await loop.run_in_executor(None, _search_sync)
                entries = data.get("entries") or []

                stop_words = [
                    "full movie", "повний фільм", "художній фільм",
                    "дивитися онлайн", "телемарафон", "єдині новини"
                ]

                for entry in entries:
                    if not entry:
                        continue

                    title = clean_title(entry.get("title"))
                    if any(w in title.lower() for w in stop_words):
                        continue

                    video_id = entry.get("id")
                    url = entry.get("url") or (
                        f"https://www.youtube.com/watch?v={video_id}" if video_id else None
                    )

                    if not url:
                        continue

                    channel = clean_title(entry.get("channel") or entry.get("uploader") or "")
                    duration_str = format_duration(entry.get("duration"))
                    display_title = f"{channel} — {title}" if channel and not title.startswith(channel) else title

                    search_results_data.append({"url": url, "title": display_title})

                    checkbox = ft.Checkbox(
                        label=f"{display_title} {duration_str}",
                        value=False,
                        expand=True,
                    )

                    play_button = ft.IconButton(
                        icon=ft.icons.PLAY_ARROW,
                        tooltip="Прослухати",
                    )

                    async def make_play_handler(target_url, btn):
                        async def handler(e_click):
                            if btn.icon == ft.icons.STOP:
                                await stop_current_audio()
                                btn.icon = ft.icons.PLAY_ARROW
                                await page.update_async()
                            else:
                                await play_audio_preview(target_url, btn)
                        return handler

                    play_button.on_click = await make_play_handler(url, play_button)

                    # ЄДИНА зміна в цьому блоці порівняно з робочою версією:
                    # кнопку програвання загорнуто в Container із ФІКСОВАНОЮ
                    # шириною (48), щоб вона більше не могла накладатись на
                    # текст назви незалежно від його довжини. Сам Row і його
                    # розташування (SPACE_BETWEEN) НЕ чіпали.
                    row_item = ft.Row(
                        controls=[checkbox, ft.Container(content=play_button, width=48)],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    )

                    results_list.controls.append(row_item)

                if search_results_data:
                    status_label.value = f"Знайдено: {len(search_results_data)} треків."
                    download_btn.disabled = False
                else:
                    status_label.value = "Нічого не знайдено."
                    download_btn.disabled = True

            except Exception as exc:
                status_label.value = "Помилка пошуку"
                page.snack_bar = ft.SnackBar(ft.Text(f"Помилка: {exc}"))
                page.snack_bar.open = True

            progress_bar.value = 0
            await set_busy(False)

        search_button.on_click = start_search
        search_input.on_submit = start_search

        async def select_all_click(e):
            for row in results_list.controls:
                if isinstance(row, ft.Row):
                    cb = row.controls[0]
                    if isinstance(cb, ft.Checkbox):
                        cb.value = True
            await page.update_async()

        async def clear_selection_click(e):
            for row in results_list.controls:
                if isinstance(row, ft.Row):
                    cb = row.controls[0]
                    if isinstance(cb, ft.Checkbox):
                        cb.value = False
            await page.update_async()

        select_all_btn.on_click = select_all_click
        clear_btn.on_click = clear_selection_click

        async def start_download(e):
            await stop_current_audio()
            selected_urls = []
            for i, row in enumerate(results_list.controls):
                if isinstance(row, ft.Row):
                    cb = row.controls[0]
                    if isinstance(cb, ft.Checkbox) and cb.value:
                        selected_urls.append(search_results_data[i]["url"])

            if not selected_urls:
                page.snack_bar = ft.SnackBar(ft.Text("Виберіть хоча б один трек!"))
                page.snack_bar.open = True
                await page.update_async()
                return

            await set_busy(True)
            progress_bar.value = 0
            status_label.value = f"Завантаження: {len(selected_urls)} треків..."
            await page.update_async()

            loop = asyncio.get_running_loop()

            def _progress_hook(d):
                if d["status"] == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    downloaded = d.get("downloaded_bytes") or 0
                    if total > 0:
                        percentage = downloaded / total
                        progress_bar.value = percentage
                        filename = os.path.basename(d.get("filename", ""))
                        status_label.value = f"Завантаження ({int(percentage * 100)}%): {filename}"
                        asyncio.run_coroutine_threadsafe(page.update_async(), loop)

                elif d["status"] == "finished":
                    progress_bar.value = 1.0
                    status_label.value = "Збереження..."
                    asyncio.run_coroutine_threadsafe(page.update_async(), loop)

            def _download_sync():
                import yt_dlp  # лінивий імпорт, помилка потрапить у except нижче
                os.makedirs(selected_folder, exist_ok=True)
                ydl_opts = {
                    "format": "bestaudio[ext=m4a]/bestaudio/best",
                    "outtmpl": os.path.join(selected_folder, "%(title)s.%(ext)s"),
                    "progress_hooks": [_progress_hook],
                    "quiet": True,
                    "no_warnings": True,
                    # ПРИБРАНО "ignoreerrors": True - саме через нього застосунок
                    # раніше рапортував "успіх", навіть якщо реально нічого не
                    # завантажилось.
                }
                saved_files = []
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    for single_url in selected_urls:
                        info = ydl.extract_info(single_url, download=True)
                        saved_files.append(ydl.prepare_filename(info))
                return saved_files

            try:
                saved_files = await loop.run_in_executor(None, _download_sync)
                existing = [f for f in saved_files if f and os.path.exists(f)]

                if len(existing) == len(selected_urls) and existing:
                    progress_bar.value = 1.0
                    status_label.value = f"Готово! Збережено {len(existing)} файл(ів) у: {selected_folder}"
                    page.snack_bar = ft.SnackBar(
                        ft.Text(f"Збережено {len(existing)} трек(ів) у {selected_folder}")
                    )
                    page.snack_bar.open = True
                elif existing:
                    status_label.value = (
                        f"Частково завершено: {len(existing)} із {len(selected_urls)} у {selected_folder}"
                    )
                    page.snack_bar = ft.SnackBar(ft.Text("Не всі треки вдалося зберегти."))
                    page.snack_bar.open = True
                else:
                    status_label.value = "Файли не збереглися. Перевірте папку та доступ до неї."
                    page.snack_bar = ft.SnackBar(ft.Text("Завантаження не вдалося зберегти на диск."))
                    page.snack_bar.open = True

            except Exception as exc:
                status_label.value = "Помилка завантаження"
                page.snack_bar = ft.SnackBar(ft.Text(f"Помилка: {exc}"))
                page.snack_bar.open = True

            await set_busy(False)

        download_btn.on_click = start_download

        page.add(
            ft.Column(
                controls=[
                    ft.Card(
                        content=ft.Container(
                            content=ft.Column([
                                ft.Text("Пошук музики", weight=ft.FontWeight.BOLD),
                                ft.Row([search_input, limit_combo, search_button]),
                                ft.Container(content=results_list, height=240),
                                ft.Row([select_all_btn, clear_btn, ft.Container(expand=True), download_btn]),
                            ]),
                            padding=10,
                        )
                    ),
                    ft.Card(
                        content=ft.Container(
                            content=ft.Column([
                                ft.Text("Папка збереження", weight=ft.FontWeight.BOLD),
                                ft.Row([folder_input, folder_button]),
                            ]),
                            padding=10,
                        )
                    ),
                    ft.Card(
                        content=ft.Container(
                            content=ft.Column([
                                ft.Text("Статус", weight=ft.FontWeight.BOLD),
                                status_label,
                                progress_bar,
                            ]),
                            padding=10,
                        )
                    ),
                ],
                expand=True,
            )
        )
    except Exception as main_err:
        page.add(ft.Text(f"Помилка запуску додатку: {main_err}", color="red", selectable=True))


if __name__ == "__main__":
    try:
        ft.app(target=main)
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()

        def error_view(page: ft.Page):
            page.add(
                ft.Text("Критична помилка при запуску:", color="red", weight="bold"),
                ft.Text(err_msg, selectable=True)
            )
        ft.app(target=error_view)
