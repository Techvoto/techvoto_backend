from django.conf import settings
from rest_framework import mixins, viewsets
from rest_framework.filters import SearchFilter
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.mail import safe_send_mail
from apps.core.permissions import IsAdminRole
from .models import ContactMessage
from .serializers import ContactCreateSerializer, ContactMessageSerializer


class ContactCreateView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'contact'

    def post(self, request):
        s = ContactCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        if data.pop('website', ''):          # bots fill the hidden field; pretend success and discard
            return Response({'detail': 'Thanks! We will get back to you soon.'}, status=201)
        msg = ContactMessage.objects.create(**data)
        safe_send_mail(f'[Techvoto contact] {msg.subject}',
                       f'From: {msg.name} <{msg.email}>\n\n{msg.message}', [settings.CONTACT_EMAIL])
        return Response({'detail': 'Thanks! We will get back to you soon.'}, status=201)


class AdminContactViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                          mixins.DestroyModelMixin, viewsets.GenericViewSet):
    queryset = ContactMessage.objects.all()
    serializer_class = ContactMessageSerializer
    permission_classes = [IsAdminRole]
    filter_backends = [SearchFilter]
    search_fields = ['name', 'email', 'subject', 'message']
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = super().get_queryset()
        handled = self.request.query_params.get('handled')
        return qs.filter(is_handled=handled == 'true') if handled in ('true', 'false') else qs
