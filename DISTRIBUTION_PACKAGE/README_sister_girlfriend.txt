================================================================================
  ROKU IPTV - PACKAGE FOR SISTER & GIRLFRIEND
================================================================================

WHAT THIS IS
------------
A free, self-hosted IPTV playlist for Roku. No subscription, no account, no
credit card. Live TV, movies, and TV shows, rebuilt daily.

It works two ways:
  1. On the Roku TV itself (via the Xtream IPTV Player app from the Channel Store)
  2. In any web browser (phone, tablet, laptop) - cast to Roku via screen mirroring

--------------------------------------------------------------------------------
STEP 1: INSTALL THE APP ON THE ROKU
--------------------------------------------------------------------------------
On the Roku home screen:
  1. Press Home, scroll to "Streaming Channels", select "Search Channels"
  2. Search for: Xtream IPTV Player   (Channel Store id 814924, it's free)
  3. Add the app, then open it

--------------------------------------------------------------------------------
STEP 2: ADD THE PLAYLIST
--------------------------------------------------------------------------------
In the Xtream IPTV Player app:
  1. Go to Settings -> Add Playlist
  2. Choose "M3U URL" (NOT the scan QR - that opens a paid vendor page)
  3. Paste this URL exactly:

     https://beexly.github.io/roku-iptv/tv.m3u

  4. Save. Live TV channels will appear under categories: News, Sports, Movies,
     Entertainment, Documentary, Kids, Music, Lifestyle, Shopping, Weather,
     International, Local, Religious, Other.

--------------------------------------------------------------------------------
STEP 3: OPTIONAL - TV GUIDE (EPG)
--------------------------------------------------------------------------------
If the app asks for a guide/EPG/XMLTV URL, paste:

     https://beexly.github.io/roku-iptv/epg.xml

This shows current and upcoming programs for channels that have guide data.

--------------------------------------------------------------------------------
STEP 4: MOVIES & TV SHOWS (VOD)
--------------------------------------------------------------------------------
The VOD shelf is in the same app under "Movies" / "Series". It includes
hundreds of public-domain films and classic TV episodes from Archive.org.

--------------------------------------------------------------------------------
ALTERNATIVE: WATCH IN A BROWSER (NO APP NEEDED)
--------------------------------------------------------------------------------
Open this page on a phone or tablet:

     https://beexly.github.io/roku-iptv/setup.html

It has the same playlist, a web player, and QR codes. Cast or mirror to the
Roku from the phone to watch on the big screen.

--------------------------------------------------------------------------------
TROUBLESHOOTING
--------------------------------------------------------------------------------
"Audio plays but video is blank":
  Some streams use codecs the Roku can't decode. The playlist is now filtered
  to Roku-compatible streams only (H.264 video, AAC/AC3 audio). If a channel
  still shows blank, try a different channel - most work fine.

"Channel not found" or "404":
  Free streams go offline sometimes. The playlist is rebuilt daily, so dead
  channels are removed automatically.

"No movies or TV shows":
  Make sure you're on the "Movies" or "Series" tab/shelf in the app, not just
  the live TV categories.

--------------------------------------------------------------------------------
URLS AT A GLANCE
--------------------------------------------------------------------------------
Playlist (M3U):   https://beexly.github.io/roku-iptv/tv.m3u
Guide (EPG):      https://beexly.github.io/roku-iptv/epg.xml
Web player:       https://beexly.github.io/roku-iptv/player.html
Setup page:       https://beexly.github.io/roku-iptv/setup.html

================================================================================
  That's it. The URLs never change - the playlist refreshes on its own.
================================================================================