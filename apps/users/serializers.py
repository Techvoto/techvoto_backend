from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import User
from apps.core.images import optimize_image

MAX_AVATAR_BYTES = 2 * 1024 * 1024


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    initials = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'full_name', 'initials', 'avatar',
                  'bio', 'role', 'xp', 'streak', 'email_verified', 'date_joined']
        # role/xp/streak/verification can never be changed by the user themselves.
        read_only_fields = ['id', 'email', 'full_name', 'initials', 'role', 'xp', 'streak', 'email_verified', 'date_joined']

    def validate_avatar(self, f):
        if f and f.size > MAX_AVATAR_BYTES:
            raise serializers.ValidationError('Avatar must be 2 MB or smaller.')
        try:
            return optimize_image(f, max_size=(512, 512), quality=80)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class PublicUserSerializer(serializers.ModelSerializer):
    """Safe subset shown to other users (instructors, discussion authors)."""
    full_name = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = ['id', 'full_name', 'avatar', 'bio', 'role']


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'password', 'password2']

    def validate_email(self, value):
        value = User.objects.normalize_email(value.strip()).lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def validate(self, data):
        if data['password'] != data['password2']:
            raise serializers.ValidationError({'password2': 'Passwords do not match.'})
        validate_password(data['password'], User(email=data['email'], first_name=data['first_name'],
                                                  last_name=data['last_name']))
        return data

    def create(self, validated_data):
        validated_data.pop('password2')
        # Registration always creates a student. Instructors are promoted by an admin.
        return User.objects.create_user(role=User.Role.STUDENT, **validated_data)


class LoginSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = UserSerializer(self.user, context=self.context).data
        return data


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_old_password(self, value):
        if not self.context['request'].user.check_password(value):
            raise serializers.ValidationError('Old password is incorrect.')
        return value

    def validate_new_password(self, value):
        validate_password(value, self.context['request'].user)
        return value


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)


class AdminUserSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'full_name', 'role', 'is_active', 'email_verified', 'xp', 'date_joined']
        read_only_fields = ['id', 'email', 'first_name', 'last_name', 'full_name', 'xp', 'date_joined']


class VerifyEmailSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
