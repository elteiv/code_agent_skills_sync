import sys
from datetime import datetime, date


def main():
    print('Hello from Python!!!!')
    with open('temp.txt', 'wt') as f:
        f.write(datetime.now().strftime('%Y%m%d-%H%M%S'))
    
if __name__ == '__main__':
    sys.exit(main())