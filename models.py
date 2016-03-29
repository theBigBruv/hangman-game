"""models.py - This file contains the class definitions for the Datastore
entities used by the Game. Because these classes are also regular Python
classes they can include methods (such as 'to_form' and 'new_game')."""

import random
import re
from datetime import date
from protorpc import messages
from google.appengine.ext import ndb


class User(ndb.Model):
    """User profile"""
    name = ndb.StringProperty(required=True)
    email =ndb.StringProperty()
    wins = ndb.IntegerProperty(default=0)
    games_played = ndb.IntegerProperty(default=0)
    total_score = ndb.IntegerProperty(default=0)

    @property
    def win_percentage(self):
        if self.games_played > 0:
            return float(self.wins)/float(self.games_played)
        else:
            return 0

    @property
    def average_score(self):
        if self.games_played > 0:
            return float(self.total_score)/float(self.games_played)
        else:
            return 0

    def to_form(self):
        return UserForm(name=self.name,
                        email=self.email,
                        wins=self.wins,
                        games_played=self.games_played,
                        total_score=self.total_score,
                        win_percentage=self.win_percentage,
                        average_score=self.average_score)

    def add_win(self, final_score):
        """Add a win"""
        self.wins += 1
        self.games_played += 1
        self.total_score += final_score
        self.put()

    def add_loss(self):
        """Add a loss"""
        self.games_played += 1
        self.put()


class Game(ndb.Model):
    """Game object"""
    target_word = ndb.StringProperty(required=True)
    target_word_length = ndb.IntegerProperty(required=True)
    correct_letters_guessed = ndb.PickleProperty(required=True)
    target_word_progress = ndb.StringProperty(required=True)
    wrong_guesses_allowed = ndb.IntegerProperty(required=True, default=10)
    wrong_guesses_remaining = ndb.IntegerProperty(required=True, default=10)
    guess_history = ndb.PickleProperty(required=True)
    game_over = ndb.BooleanProperty(required=True, default=False)
    user = ndb.KeyProperty(required=True, kind='User')

    @classmethod
    def new_game(cls, user, target_word):
        """Creates and returns a new game"""
        # insert checks for whitespaces, numerics, special characters, and minimum word length of target_word
        if not re.match("^[a-zA-Z]+$", target_word):
            raise ValueError('Target word must be a single word and must not contain any numbers or special characters')
        if len(target_word) < 8:
            raise ValueError('Target word must be at least 8 characters long')
        game = Game(user=user,
                    target_word=target_word,
                    wrong_guesses_allowed=10,
                    wrong_guesses_remaining=10,
                    game_over=False)
        game.target_word_length = len(target_word)
        game.correct_letters_guessed = []
        game.target_word_progress = "*" * len(target_word)
        game.guess_history = []
        game.put()
        return game

    def to_form(self, message):
        """Returns a GameForm representation of the Game"""
        form = GameForm()
        form.urlsafe_key = self.key.urlsafe()
        form.user_name = self.user.get().name
        form.target_word_length = self.target_word_length
        form.target_word_progress = self.target_word_progress
        form.wrong_guesses_remaining = self.wrong_guesses_remaining
        form.game_over = self.game_over
        form.message = message
        return form

    def end_game(self, won=False):
        """Ends the game - if won is True, the player won. - if won is False,
        the player lost."""
        self.game_over = True
        self.put()
        # Generate a score for the game
        score = Score(user=self.user, date=date.today(), won=won,
                      wrong_guesses=self.wrong_guesses_allowed - self.wrong_guesses_remaining,
                      final_score=self.wrong_guesses_remaining)
        score.put()
        # Update the wins and games_played property of the user
        if won:
            self.user.get().add_win(self.wrong_guesses_remaining)
        else:
            self.user.get().add_loss()


class Score(ndb.Model):
    """Score object"""
    user = ndb.KeyProperty(required=True, kind='User')
    date = ndb.DateProperty(required=True)
    won = ndb.BooleanProperty(required=True)
    wrong_guesses = ndb.IntegerProperty(required=True)
    final_score = ndb.IntegerProperty(required=True)

    def to_form(self):
        return ScoreForm(user_name=self.user.get().name, won=self.won,
                         date=str(self.date), wrong_guesses=self.wrong_guesses,
                         final_score=self.final_score)


class UserForm(messages.Message):
    """User Form"""
    name = messages.StringField(1, required=True)
    email = messages.StringField(2)
    wins = messages.IntegerField(3, required=True)
    games_played = messages.IntegerField(4, required=True)
    total_score = messages.IntegerField(5, required=True)
    win_percentage = messages.FloatField(6, required=True)
    average_score = messages.FloatField(7, required=True)


class UserForms(messages.Message):
    """Container for multiple User Forms"""
    items = messages.MessageField(UserForm, 1, repeated=True)


class GameForm(messages.Message):
    """GameForm for outbound game state information"""
    urlsafe_key = messages.StringField(1, required=True)
    target_word_length = messages.IntegerField(2, required=True)
    target_word_progress = messages.StringField(3, required=True)
    wrong_guesses_remaining = messages.IntegerField(4, required=True)
    game_over = messages.BooleanField(5, required=True)
    message = messages.StringField(6, required=True)
    user_name = messages.StringField(7, required=True)


class NewGameForm(messages.Message):
    """Used to create a new game"""
    user_name = messages.StringField(1, required=True)
    target_word = messages.StringField(2, required=True)


class GameForms(messages.Message):
    """Container for multiple GameForm"""
    items = messages.MessageField(GameForm, 1, repeated=True)


class MakeMoveForm(messages.Message):
    """Used to make a move in an existing game"""
    guess = messages.StringField(1, required=True)


class ScoreForm(messages.Message):
    """ScoreForm for outbound Score information"""
    user_name = messages.StringField(1, required=True)
    date = messages.StringField(2, required=True)
    won = messages.BooleanField(3, required=True)
    wrong_guesses = messages.IntegerField(4, required=True)
    final_score = messages.IntegerField(5, required=True)


class ScoreForms(messages.Message):
    """Return multiple ScoreForms"""
    items = messages.MessageField(ScoreForm, 1, repeated=True)


class StringMessage(messages.Message):
    """StringMessage-- outbound (single) string message"""
    message = messages.StringField(1, required=True)
