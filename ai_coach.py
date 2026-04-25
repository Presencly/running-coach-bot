"""
AI Coach system for generating coaching responses and plans.
Uses Claude API with the unified system prompt and context.
"""
import json
import re
from datetime import date, timedelta
from anthropic import Anthropic
from config import (
    CLAUDE_MODEL_CHAT,
    CLAUDE_MODEL_PLANNING,
    SYSTEM_PROMPT,
    ATHLETE_PROFILE,
    PLAN_WEEKS,
)
from database import (
    get_conversation_history,
    add_conversation_message,
    get_recent_activities,
    get_plan_week,
    get_plan_metadata,
    get_recent_gym_workouts,
    get_gym_plan_week,
)


class AiCoach:
    def __init__(self):
        self.client = Anthropic()
        self.system_prompt = SYSTEM_PROMPT

    # ── Context building ─────────────────────────────────────────────────────

    def _current_week(self):
        metadata = get_plan_metadata()
        if not metadata:
            return 1
        try:
            race_date = date.fromisoformat(metadata['race_date'])
            start_date = race_date - timedelta(weeks=PLAN_WEEKS)
            weeks_elapsed = (date.today() - start_date).days // 7 + 1
            return max(1, min(24, weeks_elapsed))
        except Exception:
            return 1

    def _get_context_data(self, deep=False):
        """Build unified running + gym context for Claude."""
        # Running activities
        limit = 20 if deep else 5
        runs = get_recent_activities(limit=limit)
        runs_text = "\n".join([
            f"{(a.get('start_date_local') or a['start_date'])[:10]}: "
            f"{a['distance_metres']/1000:.1f}km @{a['average_pace_per_km']:.2f}/km"
            + (f" HR{a['average_heartrate']:.0f}" if a['average_heartrate'] else "")
            + (f" {a['kilojoules']:.0f}kJ" if a.get('kilojoules') else "")
            for a in runs
        ]) if runs else "No recent runs"

        # Gym workouts
        gym_limit = 10 if deep else 3
        workouts = get_recent_gym_workouts(limit=gym_limit)
        gym_text = "\n".join([
            f"{(w.get('start_time') or '')[:10]}: {w['title']} "
            f"({w['duration_seconds']//60 if w.get('duration_seconds') else '?'}min)"
            for w in workouts
        ]) if workouts else "No recent gym workouts"

        # Upcoming week plan
        current_week = self._current_week()
        run_sessions = get_plan_week(current_week)
        gym_sessions = get_gym_plan_week(current_week)

        run_plan = "\n".join([
            f"{s['session_date']} {s['session_type']}"
            + (f" {s['target_distance_km']}km" if s.get('target_distance_km') else "")
            for s in run_sessions
        ]) if run_sessions else "No running sessions planned"

        gym_plan = "\n".join([
            f"{s['session_date']} {s['session_type'].replace('_', ' ')}"
            for s in gym_sessions
            if s['session_type'] not in ('rest', 'mobility')
        ]) if gym_sessions else "No gym sessions planned"

        return (
            f"Recent runs:\n{runs_text}\n\n"
            f"Recent gym workouts:\n{gym_text}\n\n"
            f"This week's running plan (week {current_week}):\n{run_plan}\n\n"
            f"This week's gym plan:\n{gym_plan}"
        )

    def _format_messages(self, user_message, include_context=True, deep_context=False):
        messages = []
        for msg in get_conversation_history():
            messages.append({"role": msg['role'], "content": msg['content']})

        if include_context:
            context = self._get_context_data(deep=deep_context)
            messages.append({
                "role": "user",
                "content": f"[CONTEXT]\n{context}\n\n[MESSAGE]\n{user_message}"
            })
        else:
            messages.append({"role": "user", "content": user_message})

        return messages

    def _needs_context(self, message):
        keywords = (
            'run', 'ran', 'today', 'week', 'session', 'plan', 'pace', 'km',
            'progress', 'strava', 'activity', 'distance', 'long', 'easy', 'tempo',
            'gym', 'workout', 'lift', 'bench', 'squat', 'deadlift', 'press',
            'pull', 'push', 'hevy', 'exercise', 'tired', 'sore', 'recover',
        )
        return any(k in message.lower() for k in keywords)

    def _needs_deep_context(self, message):
        keywords = (
            'month', 'months', 'history', 'trend', 'last 3', 'last 4', 'overall',
            'been doing', 'have i been', 'analyse', 'analyze', 'review', 'summary',
            'progress', 'stronger', 'improving',
        )
        return any(k in message.lower() for k in keywords)

    def _cached_system(self):
        return [{"type": "text", "text": self.system_prompt, "cache_control": {"type": "ephemeral"}}]

    # ── Chat ─────────────────────────────────────────────────────────────────

    def chat(self, user_message):
        needs_ctx = self._needs_context(user_message)
        messages = self._format_messages(
            user_message,
            include_context=needs_ctx,
            deep_context=self._needs_deep_context(user_message)
        )

        response = self.client.messages.create(
            model=CLAUDE_MODEL_CHAT,
            max_tokens=800,
            system=self._cached_system(),
            messages=messages
        )

        assistant_message = response.content[0].text
        add_conversation_message("user", user_message)
        add_conversation_message("assistant", assistant_message)
        return assistant_message

    # ── Plan generation ───────────────────────────────────────────────────────

    def generate_training_plan(self):
        """Generate the 24-week running plan."""
        plan_prompt = f"""
Generate a complete 24-week running plan for the Nike Melbourne Half Marathon on {ATHLETE_PROFILE['race_date']}.

Athlete: {ATHLETE_PROFILE['name']}
Current volume: {ATHLETE_PROFILE['current_volume_per_week_km']}km/week
Goal pace: {ATHLETE_PROFILE['goal_pace_per_km']:.2f}/km
Recent benchmark: {ATHLETE_PROFILE['recent_benchmark']['distance_km']}km at {ATHLETE_PROFILE['recent_benchmark']['average_pace_per_km']:.2f}/km

The plan must:
1. Gradually build from {ATHLETE_PROFILE['current_volume_per_week_km']}km to peak at ~40km/week
2. Follow this structure:
   - Weeks 1-8 (Base): All easy running, 3 runs/week. Build volume to 25-30km/week.
   - Weeks 9-16 (Development): Add 1 quality session/week, maintain easy + long runs. 35-40km/week.
   - Weeks 17-22 (Race Specific): 1-2 quality sessions/week at goal pace. Volume 35-40km/week.
   - Weeks 23-24 (Taper): Cut volume 40-50%, maintain some intensity.
3. Include variety: easy runs, tempo efforts, intervals, long runs
4. Respect the 10% rule for volume increases
5. Return as JSON: [{{"week": number, "sessions": [{{"day": number, "type": "easy|tempo|intervals|long_run|rest", "distance_km": number, "description": "string"}}]}}]

Generate all 24 weeks.
"""
        return self._call_planning(plan_prompt)

    def generate_plan_raw(self, prompt):
        """Generate any plan from a raw prompt string — used by gym_plan.py."""
        return self._call_planning(prompt)

    def _call_planning(self, prompt):
        messages = [{"role": "user", "content": prompt}]
        response = self.client.messages.create(
            model=CLAUDE_MODEL_PLANNING,
            max_tokens=8000,
            system=self._cached_system(),
            messages=messages
        )
        plan_text = response.content[0].text
        plan_data = self._extract_json(plan_text)

        if plan_data is None:
            messages.append({"role": "assistant", "content": plan_text})
            messages.append({"role": "user", "content": "Return ONLY valid JSON array, no other text."})
            response = self.client.messages.create(
                model=CLAUDE_MODEL_PLANNING,
                max_tokens=8000,
                system=self._cached_system(),
                messages=messages
            )
            plan_data = self._extract_json(response.content[0].text)

        if plan_data is None:
            raise ValueError("Could not parse plan JSON from Claude response")
        return plan_data

    def _extract_json(self, text):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        for pattern in (r'\[.*\]', r'\{.*\}'):
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    continue
        return None

    # ── Analysis ─────────────────────────────────────────────────────────────

    def analyze_run(self, activity):
        prompt = f"""Analyze this completed run and provide coaching feedback:

Distance: {activity['distance_metres']/1000:.1f}km | Pace: {activity['average_pace_per_km']:.2f}/km
Time: {activity['moving_time_seconds']/60:.0f}min | Date: {(activity.get('start_date_local') or activity['start_date'])[:10]}
HR: avg {activity['average_heartrate']:.0f} / max {activity['max_heartrate']:.0f} bpm
Elevation: {activity['total_elevation_gain']:.0f}m{f" | {activity['kilojoules']:.0f}kJ" if activity.get('kilojoules') else ""}

Keep feedback conversational. Flag if easy run HR was too high."""

        response = self.client.messages.create(
            model=CLAUDE_MODEL_CHAT,
            max_tokens=500,
            system=self._cached_system(),
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text

    def analyze_gym_workout(self, workout):
        exercises = json.loads(workout.get('exercises_json', '[]'))
        ex_summary = "\n".join([
            f"- {e.get('title', 'Unknown')}: "
            f"{len(e.get('sets', []))} sets, best 1RM est. {e.get('best_1rm', '?')}kg"
            for e in exercises[:8]
        ])
        duration = f"{workout['duration_seconds']//60}min" if workout.get('duration_seconds') else "?"

        prompt = f"""Analyze this gym workout and provide coaching feedback:

Title: {workout['title']} | Date: {(workout.get('start_time') or '')[:10]} | Duration: {duration}

Exercises:
{ex_summary}

Consider: volume, exercise selection, duration appropriateness, how it fits the running schedule.
Keep it conversational and concise."""

        response = self.client.messages.create(
            model=CLAUDE_MODEL_CHAT,
            max_tokens=500,
            system=self._cached_system(),
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text

    def suggest_plan_adjustment(self, reason):
        prompt = f"""The athlete has requested a plan adjustment. Reason: {reason}

Current training context:
{self._get_context_data()}

Suggest specific adjustments to the next 7-14 days across both running and gym. Be brief and actionable."""

        response = self.client.messages.create(
            model=CLAUDE_MODEL_PLANNING,
            max_tokens=800,
            system=self._cached_system(),
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
