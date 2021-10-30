# TwitchPubSubMirror

A Streamlabs Chatbot (SLCB) Script that uses [websocket-sharp](https://github.com/sta/websocket-sharp) to mirror events from Twitch PubSub socket, and sends them to the local SLCB socket

For a local event listner, you can install [SocketReceiver](https://github.com/nossebro/SocketReceiver), and subscribe to the `TWITCHPUBSUB` event.

Script could also be used as a stand alone template, modifying `TwitchPubSubAPIEvent` logic for PubSub topics.

## Installation

1. Login to Twitch with your streamer account, and register a new app at <https://dev.twitch.tv/console/apps>, noting the client ID. You can use <https://twitchapps.com/tokengen> as redirection URL.
2. Generate a token at <https://twitchapps.com/tokengen> using the Cliend ID from step 1, and `channel:read:redemptions channel_subscriptions bits:read channel_read` as scope. Note the token.
3. Install the script in SLCB. (Please make sure you have configured the correct [32-bit Python 2.7.13](https://www.python.org/ftp/python/2.7.13/python-2.7.13.msi) Lib-directory).
4. Run `python27.exe -m pip install https://github.com/nossebro/PythonEventTemplates/archive/refs/heads/main.zip`
5. Review the script's configuration in SLCB, providing your streamer account login, client ID and Token.
