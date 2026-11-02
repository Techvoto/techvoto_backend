from rest_framework import serializers

from .models import ContactMessage


class ContactCreateSerializer(serializers.ModelSerializer):
    website = serializers.CharField(required=False, allow_blank=True, write_only=True)   # honeypot: humans leave it empty

    class Meta:
        model = ContactMessage
        fields = ['name', 'email', 'subject', 'message', 'website']

    def validate_message(self, v):
        if len(v.strip()) < 10:
            raise serializers.ValidationError('Please write a few more words so we can help.')
        return v


class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ['id', 'name', 'email', 'subject', 'message', 'is_handled', 'created_at']
        read_only_fields = ['id', 'name', 'email', 'subject', 'message', 'created_at']
