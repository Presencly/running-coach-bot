"""
AI Coach system for generating coaching responses and plans.
Uses Claude API with the detailed system prompt and context.
"""
import json
from datetime import datetime
from anthropic import Anthropic
from config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL_CHAT,
    CLAUDE_MODEL_PLANNING,
    SYSTEM_PROMPT,
    ATHLETE_PROFILE,
    PLAN_WEEKS,
    PHASE_STRUCTURE
)
from database import (
    get_conversation_history,
    add_conversation_message,
    get_recent_activities,
    get_plan_week,
    get_plan_metadata
)


class AiCoach:
    def __init__(self):
        self.client = Anthropic()
        self.system_prompt = SYSTEM_PROMPT
    
    def _get_context_data(self):
        """Build current context about athlete's training."""
        # Recent activities
        recent_activities = get_recent_activities(limit=5)
        activities_text = "\n".join([
            f"- {a['name']}: {a['distance_metres']/1000:.1f}km at {a['average_pace_per_km']:.2f}/km pace" +
            (f" (HR: {a['average_heartrate']:.0f} avg, {a['max_heartrate']:.0f} max)" if a['average_heartrate'] else "")
            for a in recent_activities
        ]) if recent_activities else "No recent activities"
        
        # Upcoming week
        metadata = get_plan_metadata()
        current_week = metadata['current_phase'] if metadata else 1
        try:
            upcoming_week = get_plan_week(current_week)
            upcoming_text = "\n".join([
                f"- {s['session_date']} ({s['session_type']}): {s['description']}"
                for s in upcoming_week
            ]) if upcoming_week else "No upcoming sessions"
        except:
            upcoming_text = "No upcoming sessions"
        
        return f"""
## Current Training Context

### Recent Activities (Last 5 runs)
{activities_text}

### Upcoming Week
{upcoming_text}
"""
    
    def _format_messages(self, user_message, include_context=True):
        """Format conversation history for Claude."""
        messages = []
        
        # Add conversation history
        history = get_conversation_history()
        for msg in history:
            messages.append({
                "role": msg['role'],
                "content": msg['content']
            })
        
        # Add context if requested
        if include_context:
            context = self._get_context_data()
            messages.append({
                "role": "user",
                "content": f"[COACH CONTEXT]\n{context}\n\n[ATHLETE MESSAGE]\n{user_message}"
            })
        else:
            messages.append({
                "role": "user",
                "content": user_message
            })
        
        return messages
    
    def _needs_context(self, message):
        """Only fetch training context when the message is run/plan related."""
        keywords = ('run', 'ran', 'today', 'week', 'session', 'plan', 'pace', 'km',
                    'progress', 'strava', 'activity', 'distance', 'long', 'easy', 'tempo')
        return any(k in message.lower() for k in keywords)

    def _cached_system(self):
        """Return system prompt with cache_control so Anthropic caches it."""
        return [{"type": "text", "text": self.system_prompt, "cache_control": {"type": "ephemeral"}}]

    def chat(self, user_message):
        """
        Process a user message and return coaching response.
        Uses claude-haiku for cost efficiency on daily queries.
        """
        messages = self._format_messages(user_message, include_context=self._needs_context(user_message))

        response = self.client.messages.create(
            model=CLAUDE_MODEL_CHAT,
            max_tokens=1000,
            system=self._cached_system(),
            messages=messages
        )
        
        assistant_message = response.content[0].text
        
        # Store in conversation history
        add_conversation_message("user", user_message)
        add_conversation_message("assistant", assistant_message)
        
        return assistant_message
    
    def generate_training_plan(self):
        """
        Generate a complete 24-week training plan.
        Uses claude-sonnet for higher quality planning.
        """
        plan_prompt = f"""
Based on this athlete profile, generate a complete 24-week training plan for the Nike Melbourne Half Marathon on {ATHLETE_PROFILE['race_date']}.

Athlete: {ATHLETE_PROFILE['name']}
Current volume: {ATHLETE_PROFILE['current_volume_per_week_km']}km/week
Goal pace: {ATHLETE_PROFILE['goal_pace_per_km']:.2f}/km
Recent benchmark: {ATHLETE_PROFILE['recent_benchmark']['distance_km']}km at {ATHLETE_PROFILE['recent_benchmark']['average_pace_per_km']:.2f}/km

The plan must:
1. Gradually build from {ATHLETE_PROFILE['current_volume_per_week_km']}km to peak at ~40km/week
2. Follow this structure:
   - Weeks 1-8 (Base): All easy running, 3 runs/week. Build volume to 25-30km/week.
   - Weeks 9-16 (Development): Add 1 quality session/week, maintain easy + long runs. 35-40km/week. Consider 4th run if coping.
   - Weeks 17-22 (Race Specific): 1-2 quality sessions/week at goal pace. Volume 35-40km/week.
   - Weeks 23-24 (Taper): Cut volume 40-50%, maintain some intensity.
3. Include variety: easy runs, tempo efforts, intervals, long runs
4. Respect the 10% rule for volume increases
5. Return as JSON with format: {{"week": number, "sessions": [{{"day": number, "type": "easy|tempo|intervals|long_run|rest", "distance_km": number, "description": "string"}}]}}

Generate 24 weeks of detailed plan entries.
"""
        
        messages = [{
            "role": "user",
            "content": plan_prompt
        }]
        
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
            messages.append({"role": "user", "content": "Please return ONLY valid JSON array, no other text."})
            response = self.client.messages.create(
                model=CLAUDE_MODEL_PLANNING,
                max_tokens=8000,
                system=self._cached_system(),
                messages=messages
            )
            plan_data = self._extract_json(response.content[0].text)

        if plan_data is None:
            raise ValueError("Could not parse training plan JSON from Claude response")

        return plan_data

    def _extract_json(self, text):
        """Extract and parse JSON array or object from text."""
        import re
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try to find JSON array or object
        for pattern in (r'\[.*\]', r'\{.*\}'):
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    continue
        return None
    
    def analyze_run(self, activity):
        """Analyze a single activity in context of the training plan."""
        analysis_prompt = f"""
Analyze this completed run and provide coaching feedback:

Activity: {activity['name']}
Distance: {activity['distance_metres']/1000:.1f}km
Pace: {activity['average_pace_per_km']:.2f}/km
Time: {activity['moving_time_seconds']/60:.0f} minutes
Average HR: {activity['average_heartrate']:.0f} bpm if available
Max HR: {activity['max_heartrate']:.0f} bpm if available
Elevation: {activity['total_elevation_gain']:.0f}m
Date: {activity['start_date']}

Keep feedback conversational and concise. Reference specific data points. Flag any concerns (e.g., if this was supposed to be an easy run but HR was high).
"""
        
        messages = [{
            "role": "user",
            "content": analysis_prompt
        }]
        
        response = self.client.messages.create(
            model=CLAUDE_MODEL_CHAT,
            max_tokens=500,
            system=self._cached_system(),
            messages=messages
        )

        return response.content[0].text

    def suggest_plan_adjustment(self, reason):
        """
        Suggest adjustments to the training plan based on some reason
        (e.g., "athlete feels tired", "missed two sessions", "overperforming").
        Uses claude-sonnet for planning quality.
        """
        adjustment_prompt = f"""
The athlete has requested a plan adjustment. Reason: {reason}

Current phase and recent performance:
{self._get_context_data()}

Suggest specific adjustments to the plan for the next 7-14 days. Consider:
- Recovery needs if fatigued
- Increased intensity if overperforming
- Flexibility but maintain consistency toward the goal

Return your suggestion as a brief, actionable plan with specific changes.
"""
        
        messages = [{
            "role": "user",
            "content": adjustment_prompt
        }]
        
        response = self.client.messages.create(
            model=CLAUDE_MODEL_PLANNING,
            max_tokens=800,
            system=self._cached_system(),
            messages=messages
        )
        
        return response.content[0].text
