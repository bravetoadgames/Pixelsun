rm -r dist
rm pixelsun
export STATICX_ALLOW_REPATH=1
pyinstaller --onefile --noconsole pixelsun.py
staticx dist/pixelsun dist/pixelsun_static
mv dist/pixelsun_static ./pixelsun
tar -czf pixelsun-1.0-ubuntu-x86_64.tar.gz pixelsun config.txt settings.txt tom-thumb.ttf


