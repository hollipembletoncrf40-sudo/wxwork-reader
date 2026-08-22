CC = clang
CFLAGS = -O3 -framework Foundation -Wno-deprecated-declarations
TARGET = find_wxwork_keys_macos

all: $(TARGET)

$(TARGET): find_wxwork_keys_macos.c
	$(CC) $(CFLAGS) -o $(TARGET) find_wxwork_keys_macos.c

clean:
	rm -f $(TARGET) *.o

test:
	python3 test_wxwork_reader.py

.PHONY: all clean test
