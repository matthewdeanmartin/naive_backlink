# Scenarios

User consumes packages on pypi
- Literally doesn't care who is who. They read all the code they install, decompile the binaries
- OR they only run code in docker
- OR wants to turn down the risk dial from "anything goes" to "social trust", trust if meets a sniff test
  - evidence points to claims being true (claims are factually true, e.g. correct photo, correct info about user, etc)
  - if these claims aren't true, it is an elaborate hoax that took up a lot of someone's time and money
  - if code is useful, why would someone do all that work
  - At risk to highjacked accounts (real account, but user lost control of it)
  - At risk to cloned accounts (everything copied from a real account, typosquatting)
  - 
- OR trusts everyone except some category of user:
  - new users (at risk for sleeper accounts)
  - anonymous users (at risk of avoiding useful code from people with legitimate reasons or political reasons to hide)
  - users without weak account correlation (links to a blog, or other constellation of web accounts)
  - users without strong account correlation (rel-me type correlations, e.g. keybase.io, librapay, etc.)
  - users with particular type of account correlation to 
    - identity site (link to a empty blog site might not mean much, esp if content looks AI generated)
    - long lived (criminal accounts are likely short lived, or sleeper accounts)
    - evidence of normal behavior (could be highjacked)
- OR can only accept perfection, a cryptographically signed proof of real world legal identity
- OR Can only use packages that they themselves published (variation on vendorizing)

User publishes to pypi. Ordinary user publishing useful things.
- Hit or miss if they make claims of identity
- Hit or miss if their claims lead to strong forms of identity
- Wouldn't be opposed to contact, but won't get contact w/o basic identity
  - (un)solicited business offers/job offers
  - (un)solicited charity
  - bug reports (could be any channel)
  - security reports (would like a private channel)


User publishes to pypi. Someone is there, but you'll never contact them.
- Wants to be anonymous
- Posts no claims
- No amount of inspection of artifacts can reveal who the user is

User publish to pypi, but no one is there now.
- Never was anonymous
- Has died or logged off the internet or moved awa.
- No longer works at that company and the company disclaims/disinherits any package

User publishes to pypi, but is malicious
- Anonymous to hide their trail
- Public to grow trust, but they're in Somalia (with no recognized government) and not subject to any of your laws
- Public, but they are not who they say they are


