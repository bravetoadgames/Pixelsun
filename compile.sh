rm -r dist
rm pixelsun
pyinstaller --onefile pixelsun.py
staticx dist/pixelsun dist/pixelsun_static
mv dist/pixelsun_static ./pixelsun
tar -czf pixelsun-1.0-ubuntu-x86_64.tar.gz pixelsun config.txt settings.txt tom-thumb.ttf


