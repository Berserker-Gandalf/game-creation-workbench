import argparse
import os
import uvicorn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-directory')
    parser.add_argument('--launch-id')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535: parser.error('port must be between 1 and 65535')
    if args.launch_id:
        if len(args.launch_id) != 32 or any(c not in '0123456789abcdef' for c in args.launch_id): parser.error('invalid launch id')
        os.environ['WORKBENCH_LAUNCH_ID'] = args.launch_id
    if args.data_directory: os.environ['WORKBENCH_DATA'] = args.data_directory
    os.environ['WORKBENCH_URL'] = f'http://127.0.0.1:{args.port}'
    from .app import app
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port))
    app.state.server = server
    server.run()


if __name__ == '__main__':
    main()
