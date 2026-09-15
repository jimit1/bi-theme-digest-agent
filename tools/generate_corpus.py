#!/usr/bin/env python
"""Deterministic, seeded generator for the non trap mock corpus.

Reads data/mock/seed_spec.yaml (a CorpusSeedSpec) and writes everything under data/mock/
except data/mock/traps/**, which is hand written by the trap author. Same spec, same seed,
same bytes out: every random choice in this file goes through one random.Random(seed)
instance, consumed in a fixed order driven only by the spec's own lists, so two runs of the
same spec produce byte identical files.

Usage:

    python tools/generate_corpus.py --spec data/mock/seed_spec.yaml --out data/mock

See contracts/file_formats.md section 12 and 13, and contracts/README.md, for the rules this
file exists to satisfy. Nothing here invents a rule that is not already pinned there; where
this file has to make a call the spec does not pin (an account's contact name, a filler
sentence, which account gets which leftover slot), the choice is recorded as an assumption
in the B2 envelope, not buried here.
"""
from __future__ import annotations

import argparse
import json
import re
import random
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import os  # noqa: E402

os.environ.setdefault("DIGEST_CONTRACTS_DIR", str(REPO_ROOT / "contracts"))

from digest.contracts import validate  # noqa: E402

SCHEMA_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Fixed cast, not in the spec because it is prose, not a count.
# ---------------------------------------------------------------------------

STAFF = [
    # (name, title, gong_user_id, sfdc_user_id_seed)
    {"name": "Priya Natarajan", "title": "Account Executive", "gong_id": "2001", "sfdc_seed": 1},
    {"name": "Marcus Oyelaran", "title": "Customer Success Manager", "gong_id": "2002", "sfdc_seed": 2},
    {"name": "Elena Kowalczyk", "title": "Support Engineer", "gong_id": "2003", "sfdc_seed": 3},
    {"name": "Tom Bradshaw", "title": "Solutions Consultant", "gong_id": "2004", "sfdc_seed": 4},
]
STAFF_BY_NAME = {s["name"]: s for s in STAFF}
STAFF_EMAIL_DOMAIN = "momentivesoftware.example.org"

# One client contact per account. Not in any schema: used to build Gong external parties
# and the one client portal Salesforce User per account.
CONTACTS = {
    "ACC-0001": {"name": "Naomi Castellanos", "title": "Director of Membership"},
    "ACC-0002": {"name": "Renee Okafor", "title": "VP of Member Engagement"},
    "ACC-0003": {"name": "Miguel Ferreira", "title": "Director of Development"},
    "ACC-0004": {"name": "Colin Bramwell", "title": "Operations Manager"},
    "ACC-0005": {"name": "Yolanda Pruitt", "title": "Program Director"},
    "ACC-0006": {"name": "Denise Okonkwo", "title": "Executive Director"},
    "ACC-0007": {"name": "Grant Halverson", "title": "Executive Director"},
    "ACC-0008": {"name": "Simone Whitfield", "title": "Membership Chair"},
    "ACC-0009": {"name": "Owen Delacroix", "title": "Board President"},
}

# Two low importance mentions used to satisfy pii_plant.names (Harold Pemberton-Vance,
# planted by the trap author, plus these two from the generated, non trap corpus).
PLANTED_MEMBER_NAMES = ["Marguerite Odom", "Desmond Kavanagh"]
REQUIRED_PII_NAME = "Harold Pemberton-Vance"

CALL_LABEL = {
    "renewal_invoice_credit": "renewal check-in",
    "event_checkin_kiosk": "event season prep",
    "lms_scorm_support": "AMS evaluation",
    "dues_notice_deliverability": "member communications review",
    "reporting_export_limits": "reporting review",
    "accounting_gl_sync": "finance sync check-in",
    "job_board_posting_expiry": "job board check-in",
    "fundraising_pledge_reminders": "fundraising campaign review",
    "sso_provisioning_gaps": "integrations check-in",
}

# Used only to gate the one-time low importance name mention (see NAME_MENTION_FILLER
# below), not for any content pool: content pools are stage based now, not category based,
# so the same theme reads differently across two calls about two different products.
CATEGORY = {
    "renewal_invoice_credit": "renewal",
    "event_checkin_kiosk": "events",
    "lms_scorm_support": "ams_eval",
    "dues_notice_deliverability": "dues",
    "reporting_export_limits": "reporting",
    "accounting_gl_sync": "accounting",
    "job_board_posting_expiry": "jobs",
    "fundraising_pledge_reminders": "fundraising",
    "sso_provisioning_gaps": "sso",
}

# ---------------------------------------------------------------------------
# Call structure pools (rework, B2 quality pass).
#
# A generated call reads: greeting -> agenda/context -> the one planted theme discussion
# (client states the problem with concrete detail, rep asks one clarifying question, client
# answers) -> two or three unrelated realistic topics -> close. Every pool below is sized so
# that a single call can draw from it without ever repeating a sentence: greeting and closing
# pools are used ONLY in their own stage, the agenda pool is generic call-opening chatter, and
# the five off topic pools are deliberately NOT about the call's own theme, so nothing in them
# reads as a second extractable claim. pick_unique() enforces the no-repeat rule at draw time.
# ---------------------------------------------------------------------------

GREETING_EXTERNAL = [
    "Hi, thanks for hopping on, good to see you.",
    "Hey there, thanks for making time for this.",
    "Good morning, appreciate you setting this up.",
    "Hi, glad we could find a slot this week.",
    "Thanks for jumping on, it has been a busy stretch on our end.",
    "Good to connect, thanks for scheduling this.",
    "Hi, sorry if I am a minute behind, glad to be here now.",
    "Thanks for the invite, good to catch up.",
    "Hey, thanks for carving out time today.",
    "Good afternoon, appreciate you fitting us in.",
    "Hi there, thanks for getting this on the calendar.",
    "Good to see you again, thanks for making room for this.",
    "Hi, thanks for having us, ready when you are.",
    "Hey, good timing, we just wrapped our last meeting.",
]
GREETING_INTERNAL = [
    "Hi, thanks for joining, good to see you.",
    "Hey, glad we could get this on the calendar.",
    "Good morning, thanks for making time today.",
    "Hi there, appreciate you carving out a few minutes.",
    "Good to connect again, thanks for hopping on.",
    "Hey, thanks for jumping on, hope the week is going well.",
    "Hi, glad this time worked for both of us.",
    "Good afternoon, thanks for being flexible with scheduling.",
    "Hey there, good to have you.",
    "Hi, thanks for making room for this on your calendar.",
    "Good morning, appreciate you joining on short notice.",
    "Hey, thanks for sticking with this time slot.",
    "Hi, good to have you, ready to dive in whenever you are.",
    "Good to see you, thanks for prioritizing this.",
]

CLOSING_EXTERNAL = [
    "Thanks for walking through all of this with us today.",
    "Appreciate the time, we will keep an eye out for the follow up.",
    "This was helpful, thanks for making space for it.",
    "Thanks, we will loop back if anything else comes up before next time.",
    "Appreciate it, talk again soon.",
    "Thanks for covering everything, we will wait to hear back on next steps.",
    "This was a good use of the time, thanks again.",
    "Appreciate you walking us through it, we will follow up on our end too.",
    "Thanks for today, we will keep this on our radar until we hear more.",
    "Glad we got through everything on our list, thanks for the time.",
    "Appreciate the update, we will check back in before too long.",
    "Thanks so much, we will be in touch if anything changes.",
    "This covers what we needed, appreciate you making time.",
    "Thanks again, looking forward to hearing what comes next.",
]
CLOSING_INTERNAL = [
    "Thanks for walking me through all of that, I will follow up with next steps.",
    "Appreciate the detail, I will get this in front of the right people.",
    "This was really helpful, I will circle back once I have an update.",
    "Thanks for your patience, I will keep you posted on where this lands.",
    "Appreciate you covering all of this, I will follow up soon.",
    "Thanks, I will write this up and share it with the team.",
    "Good talking through this, I will be in touch with next steps.",
    "Thanks for today, I will make sure this gets tracked properly.",
    "Appreciate it, I will follow up once I hear back from our side.",
    "Thanks for the thorough rundown, I will take it from here.",
    "This gives me what I need, I will circle back shortly.",
    "Appreciate the time today, I will keep this moving on our end.",
    "Thanks again, I will send a note once there is an update.",
    "Good session today, I will follow up with next steps soon.",
]

AGENDA_EXTERNAL = [
    "Before we get into it, things have been steady on our end overall.",
    "We wanted to cover a couple of items today, one of them is a bit more pressing.",
    "Overall things are going fine, just a few things we wanted to flag.",
    "We have a short list today, nothing too complicated.",
    "It has been a fairly normal month for us, a couple of things came up though.",
    "We are mostly in a good spot, just have a few things to run by you.",
    "Nothing major on our end generally, just a couple of specific items.",
    "We wanted to use this time to walk through what has been coming up lately.",
    "Things have been busy but manageable, a few things worth mentioning.",
    "We put together a short list of items for today's call.",
    "Overall we are in decent shape, just a couple of things worth flagging.",
    "We wanted to make sure we covered a couple of open items today.",
    "Nothing urgent overall, just a short list we wanted to get through.",
    "We are doing fine day to day, a couple of specific things came up though.",
]
AGENDA_INTERNAL = [
    "Happy to go through whatever is on your list today.",
    "Let's get into it, what would you like to start with?",
    "Sounds good, I have some time blocked so we can cover everything.",
    "Let me know what is top of mind and we will work through it.",
    "Glad to hear things are generally steady, let's dig into the specifics.",
    "That sounds manageable, let's take these one at a time.",
    "I pulled up your account beforehand, so we can move through this today.",
    "Happy to take these in whatever order makes sense to you.",
    "Let's start wherever is most useful for you.",
    "Sounds good, I am ready to take notes as we go.",
    "Let me know which item you would like to prioritize first.",
    "Glad to make time for this, let's walk through the list.",
    "That works, I will follow along and flag anything I need to check on.",
    "Sounds good, let's get started.",
]

ACK_INTERNAL = [
    "That is really helpful context, thank you for walking me through it.",
    "Thanks for laying that out, I want to make sure I understand it fully.",
    "Appreciate the detail, let me ask a quick follow up.",
    "That helps a lot, I have one clarifying question.",
    "Good to know, let me dig in with one more question.",
    "Thanks for explaining that, I want to get one more detail.",
    "That makes sense, one thing I want to confirm.",
    "Appreciate you walking through that, quick question on my end.",
    "Thanks, that gives me a clearer picture, one follow up though.",
    "Good context, let me ask about one specific piece of it.",
    "That is useful, I just want to nail down one detail.",
    "Thanks for the specifics, I have a quick question before we move on.",
    "Appreciate that, let me confirm one thing before we continue.",
    "Good to hear the details, one more thing I want to ask about.",
]

# One bridge line the rep uses to move from the theme discussion into small talk. Its only
# job is to flip the side away from the client's answer without creating a second same
# speaker double, so the topic pairs that follow can always start with the client raising the
# topic and the rep reacting, in that order.
OFFTOPIC_BRIDGE_INTERNAL = [
    "Before we wrap up, how has everything else been going on your end?",
    "Switching gears for a second, anything else going on that I should know about?",
    "That covers the main item, what else has been happening on your side?",
    "Good, let's shift gears for a minute, anything else worth mentioning?",
    "Appreciate that, changing topics for a moment, how has the rest of the quarter been?",
    "Thanks, let's take a quick detour, anything else new on your end?",
    "Good to have that squared away, what else is going on for you all?",
    "Before we close out, anything else worth flagging while we have time?",
    "Let's shift focus for a bit, how have things been otherwise?",
    "Good, switching gears, anything else come up recently?",
    "Appreciate the detail there, what else has been keeping you busy?",
    "Thanks for that, let's talk about something else for a minute, how has the rest of the season been?",
]

# Off topic small talk: deliberately unrelated to the theme discussion, so nothing in here
# reads as a second extractable claim. Chosen per call from OFFTOPIC_TOPICS so the same call
# never repeats a topic, and each topic pool is large enough that a long call never repeats a
# sentence drawing from it.
OFFTOPIC_TOPICS = ["weather", "event_season", "board_meeting", "staff_changes", "conference_next_month"]

OFFTOPIC_EXTERNAL = {
    "weather": [
        "It has been unusually warm here the last couple of weeks.",
        "We got an early frost last week that caught everyone off guard.",
        "The weather has been all over the place lately, hot one day and cold the next.",
        "We had a big storm roll through over the weekend.",
        "It has been raining here for what feels like a week straight.",
        "The forecast is calling for snow later this week.",
        "We are enjoying a nice stretch of mild weather right now.",
        "It has been pretty humid here the last little while.",
        "We had a bit of flooding downtown after last week's storm.",
        "The office was closed for a day because of the ice.",
        "It has cooled off quite a bit compared to last month.",
        "We are hoping for clearer skies for the weekend.",
        "It has been windy enough here to notice it on the drive in.",
        "The heat wave finally broke earlier this week.",
        "We had our first snow of the season a few days ago.",
        "It has been a mild fall so far compared to last year.",
    ],
    "event_season": [
        "We are deep into planning for our fall conference right now.",
        "Registration for our next event opens next week.",
        "We added a session track this year to the agenda.",
        "Our event committee has been meeting weekly to finalize the schedule.",
        "We are still finalizing the venue for next spring's gathering.",
        "We just locked in the venue for the fall event.",
        "The events team has been busy getting everything ready.",
        "We are trying a new registration platform for the upcoming conference.",
        "Our annual meeting is coming up in a few weeks.",
        "The event budget got approved a little later than usual this year.",
        "We have a few sponsors lined up for the fall conference.",
        "Planning for next year's event calendar starts right after this one wraps.",
        "We moved the date up a few weeks from last year.",
        "The events team is finalizing the printed materials this week.",
        "We are finalizing the catering order for the fall event this week.",
        "The keynote speaker for the fall event confirmed their travel dates.",
    ],
    "board_meeting": [
        "We just wrapped our quarterly board meeting.",
        "Our board asked for an update on a few initiatives this month.",
        "The board approved next year's budget last week.",
        "We have a board retreat coming up in a few weeks.",
        "Our board chair has been asking about a couple of ongoing projects.",
        "The board meeting ran a little long this time.",
        "We are preparing materials for the next board session.",
        "Our board added two new members this year.",
        "We circulate a membership update to the board ahead of each meeting.",
        "We spent most of the last board meeting on strategic planning.",
        "Our executive committee meets in between the full board sessions.",
        "The board signed off on a new initiative last month.",
        "We are putting together the board packet for next week.",
        "Our board likes to review the finances at every meeting.",
        "The next board meeting is scheduled for the middle of next month.",
        "Our board has been pretty engaged with the strategic plan lately.",
    ],
    "staff_changes": [
        "We have had a bit of turnover on our team this quarter.",
        "We just brought on a new coordinator last month.",
        "One of our longtime staff members retired recently.",
        "We are still backfilling a role that opened up over the summer.",
        "Our operations lead moved into a new position internally.",
        "We added two people to the team this year.",
        "A few staff shifted departments after our reorg.",
        "We are training a new hire on our systems this week.",
        "Our development director left for another organization last month.",
        "We promoted someone from within to lead a team.",
        "It has been a season of change with a few new faces around.",
        "We are down a person on the finance team right now.",
        "Our new hire starts full time next week.",
        "A couple of part time staff moved into full time roles.",
        "We restructured a bit after a few departures this year.",
        "Our team is smaller than usual right now while we backfill a role.",
    ],
    "conference_next_month": [
        "A few of us are heading to the regional conference next month.",
        "We are finalizing our travel dates for next month's conference.",
        "Our team booked a booth at the conference happening next month.",
        "We are sharing a hotel block with a couple of other member organizations for the conference.",
        "The conference agenda for next month just came out.",
        "We are sending three people to the conference next month.",
        "Our executive director is speaking on a panel at next month's conference.",
        "We are finalizing our flights for the conference next month.",
        "A couple of board members are joining us at next month's conference.",
        "We are putting together handouts to bring to the conference.",
        "The conference is in a different city than last year, so travel takes a bit longer.",
        "We are coordinating carpools for a few of us heading to the conference.",
        "Our registration for next month's conference is already confirmed.",
        "We are looking forward to catching up with a few peers at the conference next month.",
        "The conference dates overlap with our own event a little this year, so we are juggling the calendar.",
        "We are printing name badges for our group ahead of the conference next month.",
    ],
}
OFFTOPIC_INTERNAL = {
    "weather": [
        "Sounds like quite a stretch of weather, hope it settles down soon.",
        "Good to know, glad everyone is doing okay after the frost.",
        "That sounds like a lot of back and forth, hope it evens out.",
        "Hope the storm did not cause too much trouble on your end.",
        "That is a lot of rain, hope it clears up before too long.",
        "Good to know, we will keep that in mind in case anything shifts.",
        "Glad to hear the weather is cooperating for a change.",
        "Hope the humidity breaks soon on your end.",
        "Hope the flooding did not cause any lasting trouble.",
        "Glad everyone stayed safe with the office closed for the ice.",
        "Sounds like a welcome change from last month.",
        "Hope the weekend clears up for you.",
        "Sounds like a windy stretch, hope the drive is manageable.",
        "Glad to hear the heat wave finally broke.",
        "Hope the first snow was not too disruptive.",
        "Sounds like a mild fall so far, hope it stays that way.",
    ],
    "event_season": [
        "Sounds like a lot of planning, hope it comes together smoothly.",
        "Good to know, let us know if the registration numbers change our timeline for anything.",
        "Noted, glad the agenda is coming together.",
        "Sounds like a lot of moving pieces, hope the committee has it covered.",
        "Good luck locking down the venue, let us know once it is confirmed.",
        "Noted, thanks for the update on the venue.",
        "Sounds like a busy stretch for the team.",
        "Interesting, let us know how the new platform works out logistically.",
        "Hope the annual meeting goes smoothly.",
        "Glad the budget came through, even if later than planned.",
        "Good to have sponsors lined up early.",
        "Sounds like the calendar planning never really stops for you all.",
        "Good to know, hope the earlier date works out for everyone.",
        "That is a lot of logistics, hope it comes together in time.",
        "Good to know, let us know if the catering plans change.",
        "Glad the keynote's travel is locked in.",
    ],
    "board_meeting": [
        "Sounds like a productive session, glad the board is engaged.",
        "That is good to hear, budgets can be tricky to get through.",
        "Board retreats are always a good chance to reset priorities.",
        "Let us know if we can help with anything for the board packet.",
        "Nice to have new voices on the board this year.",
        "Sounds like a full agenda, glad it all got covered.",
        "Sounds like a productive session, strategic planning always takes a while.",
        "Happy to provide any data that would help with the board report.",
        "Good to know the executive committee stays active between meetings.",
        "Nice, sounds like the board is aligned on the new initiative.",
        "Let us know if there is anything to pull together for next week.",
        "That is a healthy habit, reviewing finances regularly.",
        "Hope the next meeting goes smoothly.",
        "Sounds like a lot of board engagement lately, that is a good sign.",
        "Glad the retreat is on the calendar, those are usually worthwhile.",
        "Good to hear, let us know if anything comes out of that meeting.",
    ],
    "staff_changes": [
        "Sounds like a lot of change, hope the transition goes smoothly.",
        "Congrats to the new hire, glad you found someone.",
        "That is a big shift, let us know if training support would help.",
        "Sorry to hear about the departure, hope the backfill goes quickly.",
        "Nice that you were able to promote from within.",
        "Turnover can be tough, glad the team is adapting.",
        "Good to know, we can point any new folks to our onboarding resources.",
        "Congrats on the internal move, glad it worked out.",
        "Hope the reorg settles in without too much disruption.",
        "Glad to hear reinforcements are coming for the team.",
        "That is a lot of change at once, hope it goes well.",
        "Let us know if we can help get anyone up to speed.",
        "Sounds like a busy stretch for the team, hope it eases up soon.",
        "Good to hear you found someone for the new hire.",
        "Hope being short staffed does not last too much longer.",
        "Appreciate you letting us know, we can adjust support as needed.",
    ],
    "conference_next_month": [
        "Sounds like a good lineup, hope the travel goes smoothly.",
        "Good to know, let us know if the dates shift.",
        "Nice, hope the booth setup goes well.",
        "Good to know, that sounds like an efficient way to handle the hotel.",
        "Thanks for the heads up, let us know if the agenda affects our schedule.",
        "Good to know how many are attending, that helps with planning on our end.",
        "That sounds like a good opportunity, hope the panel goes well.",
        "Good to know, safe travels once the flights are booked.",
        "Nice that the board is joining, hope it is a good trip.",
        "Let us know if we can help with anything for the handouts.",
        "Good to know, hope the extra travel time is not too much of a hassle.",
        "Sounds like a good plan for the carpool.",
        "Good to know the registration is set.",
        "Hope you get some good time to catch up with everyone there.",
        "Good to know, let us know if the overlap causes any scheduling headaches.",
        "Let us know if there is anything on our end for the badges.",
    ],
}

# The one claim each generated call or case is allowed to carry, worded differently per
# account so synthesis has to notice the two are the same theme rather than pattern match a
# shared keyword. Index into the list by the account's position in theme_plan.accounts.
THEME_CLAIM_VARIANTS = {
    "renewal_invoice_credit": [
        "Our renewal invoice keeps landing without a line for the credit we are owed from the "
        "partial year adjustment, and finance ends up chasing it every single cycle.",
        "When one of our chapters upgrades partway through the year we get billed the full "
        "renewal amount again in the fall, with nothing knocked off for what was already collected.",
    ],
    "event_checkin_kiosk": [
        "Our onsite team needs event check-in to keep working even when the venue wifi drops, "
        "and then sync everything back once we are online again.",
        "The attendee kiosk has to keep taking people in even if the venue connection goes down, "
        "and catch back up automatically the moment it reconnects.",
    ],
    "lms_scorm_support": [
        "We need to be able to upload our existing SCORM 1.2 course packages and have them run "
        "inside the new learning module without rebuilding anything.",
        "Our training team already has a library built for SCORM 2004, so whatever we move to "
        "needs to accept that packaging directly.",
    ],
    "dues_notice_deliverability": [
        "A good number of our members tell us the renewal notice never showed up, and when we "
        "check, it landed in their spam folder instead of the inbox.",
        "Our renewal reminder emails are getting flagged as spam by some of the bigger providers, "
        "so members are missing the notice entirely.",
    ],
    "reporting_export_limits": [
        "Any report we try to export once membership crosses about ten thousand rows just cuts "
        "off partway through instead of finishing the file.",
        "Our year end donor report stops short of the full list once it gets past a few thousand "
        "rows, so we are stitching multiple exports together by hand.",
    ],
    "accounting_gl_sync": [
        "The general ledger sync has posted the same journal entry twice on more than one "
        "closing, and our bookkeeper has to go back and reverse the duplicate by hand.",
        "Every few weeks a batch of transactions shows up twice in the ledger after the sync "
        "runs, and finance has to hunt down which one to remove.",
    ],
    "job_board_posting_expiry": [
        "A posting expires and comes down with no warning to the person who placed it, so "
        "postings vanish while they still think it is live.",
        "We keep finding job postings that quietly expired days ago because nobody got a heads "
        "up that the listing was about to come down.",
    ],
    "fundraising_pledge_reminders": [
        "Pledge reminders keep going out on the standard schedule even for donors who told us "
        "they only want a single reminder before the campaign closes.",
        "We have donors who asked to be reminded by mail only, and the system still emails them "
        "pledge reminders on top of that.",
    ],
    "sso_provisioning_gaps": [
        "When someone changes roles in our identity provider the sync misses it, and they keep "
        "the old permission set until someone catches it manually.",
        "Staff who move departments still show up with their prior access weeks later because "
        "the provisioning sync does not pick up the role change.",
    ],
}

# The concrete detail that follows the claim: one extra client monologue with a member
# count, a date, a report name or an amount (the reviewer facing signal that this is a real
# conversation, not a template), one clarifying question the rep asks, and the client's
# answer. Indexed the same way as THEME_CLAIM_VARIANTS: by the account's position in the
# theme's account list. Deliberately still ONE claim per call: the detail elaborates the same
# problem, it never introduces a second, independently extractable ask.
THEME_DETAIL = {
    "renewal_invoice_credit": [
        {
            "detail": "It happened again on the October 1st renewal batch, about 340 "
                       "memberships, and the missing credit averaged around 45 dollars each.",
            "question": "Can you tell me roughly how many accounts this hit on that last "
                         "cycle, and do you have a specific invoice number or date I can pull up?",
            "answer": "The batch date was October 1st and I can send over three invoice "
                      "numbers where it happened, they all show the same missing line.",
        },
        {
            "detail": "Our Ridgeview chapter upgraded back in April, and when their November "
                      "renewal came through the full 1,200 dollar amount posted with nothing "
                      "subtracted for what they already paid.",
            "question": "Can you tell me roughly how many accounts this hit on that last "
                         "cycle, and do you have a specific invoice number or date I can pull up?",
            "answer": "It was the November 3rd renewal run, invoice C-88214, and Ridgeview's "
                      "finance lead already flagged two more from the same batch.",
        },
    ],
    "event_checkin_kiosk": [
        {
            "detail": "At our spring conference we had about 1,800 attendees come through, "
                      "and check-in went down for almost 40 minutes when the venue wifi dropped.",
            "question": "Do you know roughly how long the outage lasted and whether anyone "
                         "had to be checked in manually on paper in the meantime?",
            "answer": "It was about 40 minutes, and our two volunteers ended up writing "
                      "names on a clipboard until it came back.",
        },
        {
            "detail": "Our fall symposium runs close to 600 members through the door, and "
                      "the kiosk froze for nearly half an hour when the hotel's connection went out.",
            "question": "Do you know roughly how long the outage lasted and whether anyone "
                         "had to be checked in manually on paper in the meantime?",
            "answer": "Close to half an hour, and we lost track of at least a dozen people "
                      "who we had to look up again afterward.",
        },
    ],
    "lms_scorm_support": [
        {
            "detail": "We have about 60 SCORM 1.2 modules built up over the last eight years "
                      "covering our certification tracks.",
            "question": "How many of those packages would you need to move over on day one "
                         "versus migrate gradually?",
            "answer": "We would want at least the 15 certification modules working "
                      "immediately, the rest could follow over the first quarter.",
        },
        {
            "detail": "Our SCORM 2004 library runs close to 90 courses, built for our "
                      "teacher certification renewal program.",
            "question": "How many of those packages would you need to move over on day one "
                         "versus migrate gradually?",
            "answer": "The 20 renewal courses would need to work right away, the older "
                      "archive courses can come later.",
        },
    ],
    "dues_notice_deliverability": [
        {
            "detail": "We checked our September 15th send and about 220 of our 1,400 "
                      "members never got the notice in their inbox.",
            "question": "Do you know which email providers those members are on, big "
                         "consumer ones or something else?",
            "answer": "Most of the ones we checked were on one of the big consumer "
                      "providers, a handful were on another.",
        },
        {
            "detail": "Out of our last renewal batch on September 8th, roughly 90 of our "
                      "500 families told us the notice never arrived.",
            "question": "Do you know which email providers those members are on, big "
                         "consumer ones or something else?",
            "answer": "It was mostly one of the big consumer providers, a few smaller ones "
                      "as well.",
        },
    ],
    "reporting_export_limits": [
        {
            "detail": "Our membership export cuts off right around 10,500 rows, and the "
                      "full roster runs closer to 14,000.",
            "question": "Which specific report is that, and do you know roughly what row "
                         "count it stops at?",
            "answer": "It is the full membership roster export, and it stops right around "
                      "10,500 rows every time.",
        },
        {
            "detail": "Our year end donor report stops at about 3,200 rows even though we "
                      "have close to 5,000 donors on file.",
            "question": "Which specific report is that, and do you know roughly what row "
                         "count it stops at?",
            "answer": "It is the year end donor summary report, and it consistently cuts "
                      "off near 3,200 rows.",
        },
    ],
    "accounting_gl_sync": [
        {
            "detail": "It happened on our August close, 14 journal entries posted twice, "
                      "totaling about 8,600 dollars we had to reverse.",
            "question": "Can you tell me which close date that was and roughly how many "
                         "entries were affected?",
            "answer": "That was the August 31st close, 14 entries in total, all posted "
                      "exactly twice.",
        },
        {
            "detail": "Our July close had 9 duplicate entries come through, adding up to "
                      "roughly 4,300 dollars our bookkeeper had to back out.",
            "question": "Can you tell me which close date that was and roughly how many "
                         "entries were affected?",
            "answer": "It was the July 31st close, 9 entries, each one duplicated once.",
        },
    ],
    "job_board_posting_expiry": [
        {
            "detail": "We had a posting from one of our members expire on September 5th "
                      "with zero warning, and they only found out when someone asked why it "
                      "was gone.",
            "question": "Do you know how far in advance a warning would need to go out to "
                         "be useful for your posters?",
            "answer": "At least a week ahead would give them time to renew it before it drops.",
        },
    ],
    "fundraising_pledge_reminders": [
        {
            "detail": "We have around 140 donors who asked for a single reminder only, and "
                      "the system sent all of them the full three part schedule anyway "
                      "during our spring campaign.",
            "question": "How many donors does that affect roughly, and was this during a "
                         "specific campaign?",
            "answer": "It was about 140 donors, all during the spring campaign that closed "
                      "in May.",
        },
        {
            "detail": "About 60 of our mail only donors got the pledge reminders during the "
                      "November campaign even though they opted out of that channel entirely.",
            "question": "How many donors does that affect roughly, and was this during a "
                         "specific campaign?",
            "answer": "Around 60 donors, and it was the November campaign specifically.",
        },
    ],
    "sso_provisioning_gaps": [
        {
            "detail": "Two staff members changed departments back in August and still had "
                      "their old access as of last week when someone noticed.",
            "question": "How long did it take before anyone noticed the access had not "
                         "updated?",
            "answer": "It was almost three weeks before someone flagged it.",
        },
        {
            "detail": "One of our regional coordinators moved roles in July and kept her "
                      "prior permissions for almost six weeks before IT caught it.",
            "question": "How long did it take before anyone noticed the access had not "
                         "updated?",
            "answer": "Close to six weeks, until she tried to approve something she should "
                      "not have had access to.",
        },
    ],
}


def planted_theme_texts() -> set[str]:
    """Every sentence that belongs to a planted theme discussion: the client's claim and
    concrete detail sentences, and the client's answer sentence, across every theme and every
    account variant. Used both by build_sfdc_case (to combine comment 1) and by
    tests/test_corpus.py (to exclude the planted block from the off topic trigger word scan),
    so the two never drift apart.
    """
    texts: set[str] = set()
    for variants in THEME_CLAIM_VARIANTS.values():
        texts.update(variants)
    for entries in THEME_DETAIL.values():
        for entry in entries:
            texts.add(entry["detail"])
            texts.add(entry["answer"])
    return texts


def planted_case_comment_bodies() -> set[str]:
    """The exact comment 1 body build_sfdc_case writes for every theme and account variant:
    the claim sentence and the concrete detail sentence joined with a space, the same way
    add_comment(claim_text + " " + detail_entry["detail"], ...) builds it there. A plain text
    match on `planted_theme_texts()` alone would miss this one because it is two sentences
    joined into a single CommentBody, not two separate sentences.
    """
    bodies: set[str] = set()
    for theme_key, variants in THEME_CLAIM_VARIANTS.items():
        details = THEME_DETAIL[theme_key]
        for i, claim_text in enumerate(variants):
            detail_entry = details[i % len(details)]
            bodies.add(claim_text + " " + detail_entry["detail"])
    return bodies


# The one filler sentence per category that also plants a low importance member or donor
# name, used exactly once each across the whole corpus so pii_plant.names totals 3 with
# Harold Pemberton-Vance (planted by the trap author, not here).
NAME_MENTION_FILLER = {
    "fundraising": "We actually had one of our long time donors, %s, ask about this at the gala last month." % PLANTED_MEMBER_NAMES[0],
    "dues": "%s, one of our board members, brought this up too, more out of curiosity than anything." % PLANTED_MEMBER_NAMES[1],
}

# Rework 2 (B2 quality pass): exactly one praise claim exists in the whole corpus. It is
# planted in one filler call's off topic section, never in the planted theme block, so a
# reader still finds exactly ONE theme's worth of extractable content in this call. The
# account and week are marked in data/mock/seed_spec.yaml as a comment next to praise_slot
# (the schema for CorpusSeedSpec has additionalProperties false everywhere, so a real data
# field there would be a contract violation; this constant is the actual source of truth).
# The sentence itself avoids every trigger word tests/test_corpus.py scans for, on purpose:
# a single planted praise line should read as praise without leaning on generic adjectives,
# and it means the trigger word test does not need a special case carved out for it.
PRAISE_SLOT = {"account_id": "ACC-0002", "week": "2026-W37", "theme_key": "fundraising_pledge_reminders"}
PRAISE_TEXT = (
    "I have to say, the fundraising platform has been smooth to use with our team all "
    "season, genuinely impressed with how it holds up during a campaign push."
)

# Salesforce case thread pools (rework, B2 quality pass). Comment 1 is always the claim plus
# the theme's concrete detail sentence (built in build_sfdc_case, not drawn from a pool).
# Comment 2 is always an ACK_INTERNAL line plus the theme's clarifying question. Comment 3 is
# always the theme's answer. Everything below is optional filler drawn after that fixed core.
CASE_WORKAROUND = [
    "In the meantime, here is a workaround that should help until this is fully resolved.",
    "We have a temporary fix in place while the team works on a permanent solution.",
    "Engineering is aware and looking into a fix, I will update this case once I hear back.",
    "We can manually adjust this on our end for now while a longer term fix is worked out.",
    "I have flagged this to the product team and will follow up here with next steps.",
    "For now, here is a manual process that should get you through the next cycle.",
    "We have escalated this internally and are tracking it closely.",
    "I put in a request with our team to prioritize this, will keep this case updated.",
    "There is a short term workaround I can walk you through if that would help.",
    "This has been logged with our engineering team for review.",
    "I will keep this case open until we have a permanent fix in place.",
    "We can apply a manual correction on this specific case while the fix is in progress.",
    "I have looped in a specialist on our team to take a closer look.",
    "For now this should get you unblocked, I will follow up once there is more news.",
]
CASE_FILLER_CLIENT = [
    "Just checking in, is there any update on this?",
    "Wanted to bump this back up, any movement here?",
    "No rush, just following up before our next renewal conversation.",
    "Let us know if anything changes on our side before the next update.",
    "Following up once more in case this slipped through.",
    "Circling back on this, appreciate any update when you have one.",
    "Just wanted to keep this on your radar.",
    "Checking back in, happy to hop on a call if that is easier.",
    "Wanted to see if there has been any progress on this.",
    "Following up ahead of our next check in, any news?",
    "Just a nudge on this one, whenever you get a chance.",
    "Appreciate the patience so far, just checking where this stands.",
]
# Private (IsPublished false) internal notes: routing, a Jira style reference, a note to
# check with a colleague. Never churn language, per SHARED_corpus_plan.md T4(a).
CASE_INTERNAL_NOTES = [
    "Routing to the billing team for review, ref MOMENT-4821.",
    "Checked with Marcus before responding, matches what he saw on the renewal call.",
    "Logged as MOMENT-3390, waiting on engineering triage.",
    "Confirmed the account renewal date before responding to this one.",
    "Flagged this internally for visibility, nothing urgent yet.",
    "Reached out to Elena to confirm the timeline before replying.",
    "Assigning to the integrations queue, tracking under MOMENT-5102.",
    "Double checked with the account team, nothing else pending here.",
    "Pulled in Tom for a second opinion on the technical side.",
    "Created MOMENT-4477 to track this on the engineering backlog.",
    "Checked the account history, this has not come up before.",
    "Looping in Priya since she owns this account relationship.",
    "Noted for the account file, nothing else to add right now.",
    "Confirmed with the support lead this matches a known pattern.",
]


# ---------------------------------------------------------------------------
# Id helpers. Deterministic, disjoint from every id the trap author was handed in
# SHARED_corpus_plan.md and contracts/file_formats.md section 13.
# ---------------------------------------------------------------------------

def gong_call_id(counter: int) -> str:
    return "778293445" + str(2000 + counter).zfill(4)


def sfdc_id(prefix3: str, counter: int) -> str:
    body = format(counter, "x").rjust(15, "0")
    return (prefix3 + body)[:18]


def case_number(counter: int) -> str:
    return str(5000 + counter).zfill(8)


# ---------------------------------------------------------------------------
# Spec loading and derived structures
# ---------------------------------------------------------------------------

def load_spec(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)
    validate(spec, "CorpusSeedSpec")
    return spec


def week_bounds(spec: dict) -> dict[str, tuple[str, str]]:
    return {w["label"]: (w["start"], w["end"]) for w in spec["calendar"]["weeks"]}


def week_of_day(spec: dict, day: str) -> str:
    for w in spec["calendar"]["weeks"]:
        if w["start"] <= day <= w["end"]:
            return w["label"]
    raise ValueError("day %s is not inside any pinned week" % day)


def ingestion_days_for_week(spec: dict, week: str) -> list[str]:
    start, end = week_bounds(spec)[week]
    return [d for d in spec["calendar"]["ingestion_days"] if start <= d <= end]


def trap_counts(spec: dict) -> dict[tuple[str, str, str], int]:
    """(theme_key, week, kind) -> number of trap slots occupying that theme's week."""
    counts: dict[tuple[str, str, str], int] = {}
    for slot in spec["trap_slots"]:
        key = (slot["theme_key"], slot["week"], slot["kind"])
        counts[key] = counts.get(key, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# accounts.json, salesforce/users.json, pii_names.json
# ---------------------------------------------------------------------------

def build_accounts_file(spec: dict) -> dict:
    accounts = []
    for a in spec["accounts"]:
        accounts.append({
            "account_id": a["account_id"],
            "account_type": a["account_type"],
            "domain": a["domain"],
            "record": {
                "attributes": {
                    "type": "Account",
                    "url": "/services/data/v62.0/sobjects/Account/%s" % a["sfdc_account_id"],
                },
                "Id": a["sfdc_account_id"],
                "Name": a["name"],
                "Tier__c": a["tier"].capitalize(),
                "ARR__c": a["arr_usd"],
                "Renewal_Date__c": a["renewal_date"],
                "Products__c": ";".join(a["products"]),
            },
        })
    return {"schema_version": SCHEMA_VERSION, "accounts": accounts}


def build_users_file(spec: dict) -> tuple[dict, dict[str, str], dict[str, str]]:
    """Returns (SalesforceQueryResponse doc, staff_name -> User Id, account_id -> contact User Id)."""
    records = []
    staff_ids: dict[str, str] = {}
    for s in STAFF:
        uid = sfdc_id("005", s["sfdc_seed"])
        staff_ids[s["name"]] = uid
        records.append({
            "attributes": {"type": "User", "url": "/services/data/v62.0/sobjects/User/%s" % uid},
            "Id": uid,
            "Name": s["name"],
            "UserType": "Standard",
            "IsActive": True,
        })
    contact_ids: dict[str, str] = {}
    for i, a in enumerate(spec["accounts"], start=1):
        uid = sfdc_id("005", 100 + i)
        contact_ids[a["account_id"]] = uid
        # SalesforceQueryResponse.schema.json's User enum has no "PowerCustomerSuccess"
        # value (SHARED_corpus_plan.md names it, the schema does not); CustomerSuccess is
        # the closest enum member and, like CspLitePortal, is not "Standard", so it still
        # resolves to speaker_side "client" per contracts/README.md assumption 3.
        user_type = "CspLitePortal" if i % 2 == 0 else "CustomerSuccess"
        records.append({
            "attributes": {"type": "User", "url": "/services/data/v62.0/sobjects/User/%s" % uid},
            "Id": uid,
            "Name": CONTACTS[a["account_id"]]["name"],
            "UserType": user_type,
            "IsActive": True,
        })
    weeks = spec["calendar"]["weeks"]
    window_from = weeks[0]["start"] + "T00:00:00Z"
    window_to = weeks[-1]["end"] + "T23:59:59Z"
    doc = {
        "schema_version": SCHEMA_VERSION,
        "totalSize": len(records),
        "done": True,
        "records": records,
        "meta": {
            "window": {"from": window_from, "to": window_to},
            "rows_returned": len(records),
            "row_cap": 200,
            "withheld_comment_count": None,
            "fields_allowlisted": ["Id", "Name", "UserType", "IsActive"],
            "soql": "SELECT Id, Name, UserType, IsActive FROM User",
        },
    }
    return doc, staff_ids, contact_ids


def build_pii_names_file(extra_names: set[str]) -> dict:
    names = sorted(set(PLANTED_MEMBER_NAMES) | {REQUIRED_PII_NAME} | extra_names)
    return {"schema_version": SCHEMA_VERSION, "names": names}


# ---------------------------------------------------------------------------
# Shared helpers: no-repeat sentence draws and the alternating speaker plan.
# ---------------------------------------------------------------------------

def pick_unique(rng: random.Random, pool: list[str], used: set[str]) -> str:
    """Draw one sentence from pool that has not been used yet in this call or case. Every
    pool below is sized so this never runs dry for a single call or case thread; if it does,
    that is a sizing bug in the pool, not something to paper over with a repeat."""
    candidates = [s for s in pool if s not in used]
    if not candidates:
        raise RuntimeError("sentence pool exhausted, needs more entries: %r" % pool[:1])
    choice = rng.choice(candidates)
    used.add(choice)
    return choice


def opposite(side: str) -> str:
    return "staff" if side == "client" else "client"


def build_call_plan(
    rng: random.Random,
    theme_key: str,
    detail_entry: dict,
    category: str,
    name_mentions_used: set[str],
    is_praise_slot: bool = False,
) -> list[tuple[str, list[str]]]:
    """Returns the ordered monologue plan for one call: a list of (side, sentences) pairs,
    side is 'client' or 'staff'. Sides strictly alternate except for exactly one deliberate
    double (the client stating the claim, then the client adding concrete detail), which is
    how a real speaker holds the floor for two turns in a row while still respecting the one
    per call limit. No sentence is drawn twice: `used` is local to this call.
    """
    used: set[str] = set()
    plan: list[tuple[str, list[str]]] = []

    def draw(side: str, count: int) -> list[str]:
        pool = GREETING_EXTERNAL if side == "client" else GREETING_INTERNAL
        return [pick_unique(rng, pool, used) for _ in range(count)]

    # 1. Greeting: exactly two monologues, rep and client, in a randomly chosen order.
    start_side = rng.choice(["client", "staff"])
    plan.append((start_side, draw(start_side, rng.randint(1, 2))))
    plan.append((opposite(start_side), draw(opposite(start_side), rng.randint(1, 2))))
    last_side = plan[-1][0]

    # 2. Agenda / context: 2 to 4 monologues, alternating, forced to land on 'staff' so the
    # claim (always 'client') that follows is a normal alternation, not a second double.
    agenda_start = opposite(last_side)
    if agenda_start == "staff":
        n_agenda = 3
    else:
        n_agenda = rng.choice([2, 4])
    agenda_sides = []
    side = agenda_start
    for _ in range(n_agenda):
        agenda_sides.append(side)
        side = opposite(side)
    for side in agenda_sides:
        pool_ext, pool_int = AGENDA_EXTERNAL, AGENDA_INTERNAL
        pool = pool_ext if side == "client" else pool_int
        plan.append((side, [pick_unique(rng, pool, used) for _ in range(rng.randint(1, 2))]))
    assert agenda_sides[-1] == "staff"

    # 3. The one planted theme discussion: client states the claim, client adds concrete
    # detail (the deliberate double), staff acknowledges and asks one clarifying question,
    # client answers. Claim and detail text are fixed per account and theme, not pool draws,
    # so they still count against `used` to keep the no-repeat guarantee call wide.
    plan.append(("client", [detail_entry["claim"]]))
    used.add(detail_entry["claim"])
    plan.append(("client", [detail_entry["detail"]]))
    used.add(detail_entry["detail"])
    ack = pick_unique(rng, ACK_INTERNAL, used)
    plan.append(("staff", [ack, detail_entry["question"]]))
    used.add(detail_entry["question"])
    plan.append(("client", [detail_entry["answer"]]))
    used.add(detail_entry["answer"])
    last_side = "client"

    # 4. Two or three unrelated but realistic topics, none of them carrying a second claim.
    # Total monologue count is picked first (25 to 60, the contract range) so the off topic
    # section absorbs whatever is left after the fixed sections above.
    final_total = rng.randint(25, 60)
    n_close = 2
    fixed_so_far = len(plan)
    n_offtopic = max(final_total - fixed_so_far - n_close, 4)

    topics = rng.sample(OFFTOPIC_TOPICS, k=rng.choice([2, 3]))
    name_mention_key = category if category in NAME_MENTION_FILLER else None
    use_name_mention = bool(
        name_mention_key
        and name_mention_key not in name_mentions_used
        and rng.random() < 0.5
    )

    # The rep bridges from the theme discussion into small talk. This both reads naturally
    # (moving on from a support ask to "anything else going on?") and flips the side away
    # from the client's answer, so every topic pair below can start with the client raising
    # the topic and the rep reacting to it, never the other way around.
    off_side = opposite(last_side)
    plan.append((off_side, [pick_unique(rng, OFFTOPIC_BRIDGE_INTERNAL, used)]))
    off_side = opposite(off_side)

    remaining = n_offtopic - 1
    name_mention_at = rng.randrange(remaining) if use_name_mention else None
    # The one praise slot for the whole corpus (see PRAISE_SLOT): pick uniformly among the
    # positions that land on the client side in this call, so the praise line always lands
    # as something the client says, never something the rep says back to them.
    praise_at = None
    if is_praise_slot:
        client_positions = [
            i for i in range(remaining)
            if (off_side if i % 2 == 0 else opposite(off_side)) == "client"
        ]
        if client_positions:
            praise_at = rng.choice(client_positions)
    for i in range(remaining):
        # Group into pairs so every topic gets pulled from both its pools roughly evenly:
        # side flips every monologue regardless of topic, so cycling the topic once per pair
        # (rather than once per monologue) keeps that from correlating with the side flip and
        # starving one side's pool when there are exactly two topics.
        topic = topics[(i // 2) % len(topics)]
        if i == praise_at:
            used.add(PRAISE_TEXT)
            plan.append(("client", [PRAISE_TEXT]))
        elif i == name_mention_at and off_side == "client":
            text = NAME_MENTION_FILLER[name_mention_key]
            used.add(text)
            plan.append(("client", [text]))
            name_mentions_used.add(name_mention_key)
        else:
            pool = OFFTOPIC_EXTERNAL[topic] if off_side == "client" else OFFTOPIC_INTERNAL[topic]
            plan.append((off_side, [pick_unique(rng, pool, used)]))
        off_side = opposite(off_side)
    last_side = plan[-1][0]

    # 5. Close: next steps and thanks, two monologues, alternating.
    close_start = opposite(last_side)
    plan.append((close_start, draw_closing(rng, close_start, used)))
    plan.append((opposite(close_start), draw_closing(rng, opposite(close_start), used)))

    return plan


def draw_closing(rng: random.Random, side: str, used: set[str]) -> list[str]:
    pool = CLOSING_EXTERNAL if side == "client" else CLOSING_INTERNAL
    return [pick_unique(rng, pool, used) for _ in range(rng.randint(1, 2))]


# ---------------------------------------------------------------------------
# Transcript timeline: n monologues, monotonic ms, total scaled to a target duration.
# ---------------------------------------------------------------------------

def build_timeline(
    rng: random.Random, sentence_counts: list[int]
) -> tuple[list[list[tuple[int, int]]], int]:
    target_ms = rng.randint(20, 45) * 60000

    raw: list[list[tuple[int, int]]] = []
    cursor = 0
    for n_sent in sentence_counts:
        spans = []
        for _ in range(n_sent):
            length = rng.randint(1, 10)
            start = cursor
            end = cursor + length
            spans.append((start, end))
            cursor = end
        cursor += rng.randint(1, 3)
        raw.append(spans)

    raw_total = cursor
    scale = target_ms / raw_total if raw_total else 1.0

    out: list[list[tuple[int, int]]] = []
    prev_end = -1
    for spans in raw:
        new_spans = []
        for start, end in spans:
            ns = int(round(start * scale))
            ne = int(round(end * scale))
            if ns <= prev_end:
                ns = prev_end + 1
            if ne <= ns:
                ne = ns + 1
            new_spans.append((ns, ne))
            prev_end = ne
        out.append(new_spans)
    return out, target_ms


# ---------------------------------------------------------------------------
# Gong call generation
# ---------------------------------------------------------------------------

def build_gong_call(
    spec: dict,
    job: dict,
    call_id: str,
    rng: random.Random,
    name_mentions_used: set[str],
) -> tuple[dict, str]:
    account = job["account"]
    account_id = account["account_id"]
    theme_key = job["theme_key"]
    accounts_for_theme = job["theme_accounts"]
    variant_index = accounts_for_theme.index(account_id) % len(THEME_CLAIM_VARIANTS[theme_key])
    claim_text = THEME_CLAIM_VARIANTS[theme_key][variant_index]
    detail_source = THEME_DETAIL[theme_key][variant_index % len(THEME_DETAIL[theme_key])]
    detail_entry = dict(detail_source, claim=claim_text)
    category = CATEGORY[theme_key]
    is_praise_slot = (
        account_id == PRAISE_SLOT["account_id"]
        and job["week"] == PRAISE_SLOT["week"]
        and theme_key == PRAISE_SLOT["theme_key"]
    )

    is_prospect = account["account_type"] == "prospect"
    contact = CONTACTS[account_id]
    ext_party_id = "p-c%s" % account_id[-2:]
    ext_speaker_id = "c-%s" % account_id[-2:]
    ext_email = "%s@%s" % (contact["name"].lower().replace(" ", "."), account["domain"])

    if is_prospect:
        internal_staff = [STAFF_BY_NAME["Priya Natarajan"], STAFF_BY_NAME["Tom Bradshaw"]]
        direction = "Outbound"
    else:
        internal_staff = [STAFF_BY_NAME["Marcus Oyelaran"]]
        direction = "Conference"

    parties = [{
        "id": ext_party_id,
        "emailAddress": ext_email,
        "name": contact["name"],
        "title": contact["title"],
        "userId": None,
        "speakerId": ext_speaker_id,
        "context": [],
        "affiliation": "External",
    }]
    internal_speaker_ids = []
    for staff in internal_staff:
        parties.append({
            "id": "p-%s" % staff["gong_id"],
            "emailAddress": "%s@%s" % (staff["name"].lower().replace(" ", "."), STAFF_EMAIL_DOMAIN),
            "name": staff["name"],
            "title": staff["title"],
            "userId": staff["gong_id"],
            "speakerId": staff["gong_id"],
            "context": [],
            "affiliation": "Internal",
        })
        internal_speaker_ids.append(staff["gong_id"])

    plan = build_call_plan(
        rng, theme_key, detail_entry, category, name_mentions_used, is_praise_slot
    )
    sentence_counts = [len(texts) for _side, texts in plan]
    rng2 = random.Random(rng.random())  # keep the outer stream advancing exactly once
    timeline, target_ms = build_timeline(rng2, sentence_counts)

    transcript_blocks = []
    for (side, texts), spans in zip(plan, timeline):
        speaker_id = ext_speaker_id if side == "client" else rng.choice(internal_speaker_ids)
        sentences = [
            {"start": s, "end": e, "text": t}
            for (s, e), t in zip(spans, texts)
        ]
        transcript_blocks.append({
            "speakerId": speaker_id,
            "topic": None,
            "sentences": sentences,
        })

    day = job["day"]
    hour = 9 + (rng.randint(0, 7))
    minute = rng.choice([0, 15, 30, 45])
    scheduled = "%sT%02d:%02d:00Z" % (day, hour, minute)
    started_second = rng.randint(30, 180)
    started_minute = minute + started_second // 60
    started_hour = hour + started_minute // 60
    started = "%sT%02d:%02d:%02dZ" % (day, started_hour % 24, started_minute % 60, started_second % 60)
    duration_seconds = int(round(target_ms / 1000))
    host = internal_staff[0]

    title = "%s - %s" % (account["name"], CALL_LABEL[theme_key])
    metadata = {
        "id": call_id,
        "url": "https://gong.invalid/call?id=%s" % call_id,
        "title": title,
        "scheduled": scheduled,
        "started": started,
        "duration": duration_seconds,
        "primaryUserId": host["gong_id"],
        "direction": direction,
        "system": "Gong",
        "scope": "External",
        "media": rng.choice(["Video", "Audio"]),
        "language": "eng",
        "workspaceId": "9911",
        "sdrDisposition": None,
        "clientUniqueId": None,
        "customData": None,
        "purpose": CALL_LABEL[theme_key],
        "meetingUrl": None,
        "isPrivate": False,
        "calendarEventId": "cal-%s" % call_id[-6:],
    }

    doc = {
        "schema_version": SCHEMA_VERSION,
        "call": {"metaData": metadata, "parties": parties},
        "transcript": {"callId": call_id, "transcript": transcript_blocks},
    }
    return doc, started


# ---------------------------------------------------------------------------
# Salesforce case generation
# ---------------------------------------------------------------------------


def _subject_from_claim(claim_text):
    """A case subject in the account's own words: the first clause of its planted claim,
    capped at 70 characters, so no two accounts share a subject and the subject never
    names the theme for the reader."""
    clause = re.split(r"[,.;]", claim_text, 1)[0].strip()
    words = clause.split()
    if len(words) > 9:
        words = words[:9]
        while words and words[-1].lower() in ("we", "the", "a", "an", "of", "to", "and", "our", "it", "is", "by", "for", "in", "on", "that", "when", "once", "about"):
            words.pop()
    clause = " ".join(words)
    return clause[0].upper() + clause[1:]

def build_sfdc_case(
    spec: dict,
    job: dict,
    case_id: str,
    case_num: str,
    comment_counter_start: int,
    rng: random.Random,
) -> tuple[dict, str, int]:
    account = job["account"]
    account_id = account["account_id"]
    theme_key = job["theme_key"]
    accounts_for_theme = job["theme_accounts"]
    variant_index = accounts_for_theme.index(account_id) % len(THEME_CLAIM_VARIANTS[theme_key])
    claim_text = THEME_CLAIM_VARIANTS[theme_key][variant_index]
    detail_entry = THEME_DETAIL[theme_key][variant_index % len(THEME_DETAIL[theme_key])]
    theme = job["theme"]

    day = job["day"]
    hour = 9 + rng.randint(0, 7)
    minute = rng.choice([0, 10, 20, 30, 40, 50])
    created = "%sT%02d:%02d:%02dZ" % (day, hour, minute, rng.randint(0, 59))

    status = rng.choices(["New", "Working", "Escalated", "Closed"], weights=[0.15, 0.45, 0.25, 0.15])[0]
    priority = rng.choices(["High", "Medium", "Low"], weights=[0.3, 0.5, 0.2])[0]
    closed_date = None
    if status == "Closed":
        closed_date = "%sT%02d:%02d:%02dZ" % (day, (hour + rng.randint(1, 9)) % 24, minute, 0)

    case = {
        "attributes": {"type": "Case", "url": "/services/data/v62.0/sobjects/Case/%s" % case_id},
        "Id": case_id,
        "CaseNumber": case_num,
        "AccountId": account["sfdc_account_id"],
        "Subject": _subject_from_claim(claim_text),
        "Status": status,
        "Priority": priority,
        "CreatedDate": created,
        "ClosedDate": closed_date,
    }

    contact = CONTACTS[account_id]
    contact_uid = job["contact_ids"][account_id]
    staff_choice = rng.choice([STAFF_BY_NAME["Marcus Oyelaran"], STAFF_BY_NAME["Elena Kowalczyk"]])
    staff_uid = job["staff_ids"][staff_choice["name"]]

    comments = []
    counter = comment_counter_start

    def comment_time(offset_minutes: int) -> str:
        total = hour * 60 + minute + offset_minutes
        h = (total // 60) % 24
        m = total % 60
        return "%sT%02d:%02d:%02dZ" % (day, h, m, rng.randint(0, 59))

    def add_comment(body: str, published: bool, author_uid: str, offset: int) -> None:
        nonlocal counter
        counter += 1
        comments.append({
            "attributes": {
                "type": "CaseComment",
                "url": "/services/data/v62.0/sobjects/CaseComment/%s" % sfdc_id("00a", counter),
            },
            "Id": sfdc_id("00a", counter),
            "ParentId": case_id,
            "CommentBody": body,
            "IsPublished": published,
            "CreatedById": author_uid,
            "CreatedDate": comment_time(offset),
        })

    # Comment 1: the client describing the problem with a concrete example, what happened and
    # roughly what they expected instead. Same claim wording as the account's calls for this
    # theme, plus the theme's concrete detail sentence (member count, date, report name or
    # amount), so this reads as one coherent example rather than a bare assertion.
    used: set[str] = {claim_text, detail_entry["detail"]}
    add_comment(claim_text + " " + detail_entry["detail"], True, contact_uid, 5)

    # Comment 2: staff acknowledges and asks the one clarifying question for this theme.
    ack = pick_unique(rng, ACK_INTERNAL, used)
    add_comment(ack + " " + detail_entry["question"], True, staff_uid, 20)
    used.add(detail_entry["question"])

    # Comment 3: the client answers with more detail.
    add_comment(detail_entry["answer"], True, contact_uid, 45)
    used.add(detail_entry["answer"])

    offset = 70
    # Comment 4 (optional): exactly one of a staff workaround/status update or a client
    # follow up nudge, never both, so the thread never exceeds six comments.
    pick = rng.random()
    if pick < 0.45:
        add_comment(pick_unique(rng, CASE_WORKAROUND, used), True, staff_uid, offset)
        offset += rng.randint(60, 300)
    elif pick < 0.70:
        add_comment(pick_unique(rng, CASE_FILLER_CLIENT, used), True, contact_uid, offset)
        offset += rng.randint(30, 200)

    # Private (IsPublished false) internal notes: routing, a ticket style reference, a note
    # to check with a colleague, never churn language (that sentence belongs to the trap
    # fixtures, not here). Roughly a third of cases carry at least one.
    if rng.random() < (1.0 / 3.0):
        add_comment(pick_unique(rng, CASE_INTERNAL_NOTES, used), False, staff_uid, 12)
        if rng.random() < 0.15:
            add_comment(pick_unique(rng, CASE_INTERNAL_NOTES, used), False, staff_uid, offset + 10)

    comments.sort(key=lambda c: c["CreatedDate"])

    doc = {"schema_version": SCHEMA_VERSION, "case": case, "comments": comments}
    return doc, created, counter


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def build_jobs(spec: dict) -> list[dict]:
    """One entry per generated (non trap) call or case, in a fixed, spec driven order."""
    tcounts = trap_counts(spec)
    jobs: list[dict] = []
    accounts_by_id = {a["account_id"]: a for a in spec["accounts"]}

    for theme in spec["theme_plan"]:
        theme_key = theme["key"]
        theme_accounts = theme["accounts"]
        cursor = 0
        for vol in theme["volumes"]:
            week = vol["week"]
            days = ingestion_days_for_week(spec, week)
            n_calls = vol["calls"] - tcounts.get((theme_key, week, "gong_call"), 0)
            n_cases = vol["cases"] - tcounts.get((theme_key, week, "sfdc_case"), 0)
            for _ in range(n_calls):
                account_id = theme_accounts[cursor % len(theme_accounts)]
                cursor += 1
                day = days[cursor % len(days)]
                jobs.append({
                    "kind": "gong_call",
                    "theme_key": theme_key,
                    "theme": theme,
                    "theme_accounts": theme_accounts,
                    "account": accounts_by_id[account_id],
                    "week": week,
                    "day": day,
                })
            for _ in range(n_cases):
                account_id = theme_accounts[cursor % len(theme_accounts)]
                cursor += 1
                day = days[cursor % len(days)]
                jobs.append({
                    "kind": "sfdc_case",
                    "theme_key": theme_key,
                    "theme": theme,
                    "theme_accounts": theme_accounts,
                    "account": accounts_by_id[account_id],
                    "week": week,
                    "day": day,
                })
    return jobs


def generate(spec: dict) -> dict[str, Any]:
    """Builds every output document in memory. Returns a dict of relative path -> object,
    plus '_pii_names' and '_index' are included in the same mapping under their real paths."""
    rng = random.Random(spec["seed"])

    accounts_file = build_accounts_file(spec)
    users_file, staff_ids, contact_ids = build_users_file(spec)

    jobs = build_jobs(spec)

    outputs: dict[str, Any] = {}
    index_entries = []
    name_mentions_used: set[str] = set()
    comment_counter = 0

    call_counter = 0
    case_counter = 0

    for job in jobs:
        job["staff_ids"] = staff_ids
        job["contact_ids"] = contact_ids
        if job["kind"] == "gong_call":
            call_counter += 1
            call_id = gong_call_id(call_counter)
            doc, occurred_at = build_gong_call(spec, job, call_id, rng, name_mentions_used)
            path = "gong/calls/%s.json" % call_id
            outputs[path] = doc
            index_entries.append({
                "path": path,
                "kind": "gong_call",
                "id": call_id,
                "account_id": job["account"]["account_id"],
                "occurred_at": occurred_at,
                "day": job["day"],
                "week": job["week"],
                "theme_key": job["theme_key"],
                "trap": False,
            })
        else:
            case_counter += 1
            case_id = sfdc_id("500", case_counter)
            case_num = case_number(case_counter)
            doc, occurred_at, comment_counter = build_sfdc_case(
                spec, job, case_id, case_num, comment_counter, rng
            )
            path = "salesforce/cases/%s.json" % case_id
            outputs[path] = doc
            index_entries.append({
                "path": path,
                "kind": "sfdc_case",
                "id": case_id,
                "account_id": job["account"]["account_id"],
                "occurred_at": occurred_at,
                "day": job["day"],
                "week": job["week"],
                "theme_key": job["theme_key"],
                "trap": False,
            })

    for slot in spec["trap_slots"]:
        time_suffix = "T15:00:00Z" if slot["kind"] == "gong_call" else "T14:00:00Z"
        index_entries.append({
            "path": slot["path"],
            "kind": slot["kind"],
            "id": slot["id"],
            "account_id": slot["account_id"],
            "occurred_at": slot["day"] + time_suffix,
            "day": slot["day"],
            "week": slot["week"],
            "theme_key": slot["theme_key"],
            "trap": True,
        })

    index_entries.sort(key=lambda e: (e["occurred_at"], e["id"]))

    generated_at = spec["calendar"]["ingestion_days"][0] + "T09:00:00Z"
    index_doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "seed": spec["seed"],
        "entries": index_entries,
    }

    pii_doc = build_pii_names_file(set())

    outputs["accounts.json"] = accounts_file
    outputs["salesforce/users.json"] = users_file
    outputs["pii_names.json"] = pii_doc
    outputs["index.json"] = index_doc
    return outputs


SCHEMA_FOR_PATH = {
    "accounts.json": "MockAccountsFile",
    "salesforce/users.json": "SalesforceQueryResponse",
    "pii_names.json": "PiiNames",
    "index.json": "MockIndex",
}


def schema_for(path: str) -> str:
    if path in SCHEMA_FOR_PATH:
        return SCHEMA_FOR_PATH[path]
    if path.startswith("gong/calls/"):
        return "GongCallFile"
    if path.startswith("salesforce/cases/"):
        return "SalesforceCaseFile"
    raise ValueError("no schema mapping for %s" % path)


def write_outputs(outputs: dict[str, Any], out_dir: Path) -> list[Path]:
    written = []
    for rel_path, doc in outputs.items():
        validate(doc, schema_for(rel_path))
        dest = out_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
        dest.write_text(text, encoding="utf-8")
        written.append(dest)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", default="data/mock/seed_spec.yaml")
    parser.add_argument("--out", default="data/mock")
    args = parser.parse_args(argv)

    spec_path = Path(args.spec)
    out_dir = Path(args.out)

    spec = load_spec(spec_path)
    outputs = generate(spec)
    written = write_outputs(outputs, out_dir)
    print("wrote %d files under %s" % (len(written), out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
