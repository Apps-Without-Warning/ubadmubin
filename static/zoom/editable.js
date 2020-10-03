function editable() {
    // Check browser support of <input type="datetime-local">, <input type="date">, etc
    // Will be an array of the supported types
    var input_support = (function() {
        function try_it(arr, type) {
            var input = document.createElement('input');
            var value = 'a';
            input.setAttribute('type', type);
            input.setAttribute('value', value);
            if (input.value !== value) {
                arr.push(type);
            }
        }

        var support = ['text', 'textarea']; // everybody supports these, I hope
        try_it(support, 'datetime-local');
        try_it(support, 'date');
        try_it(support, 'time');
        return support;
    })();

    var to_html = {
        'date': function (date_str) {
            var months = ['Jan.', 'Feb.', 'March', 'April', 'May', 'June', 'July', 'Aug.', 'Sept.', 'Oct.', 'Nov.', 'Dec.']; // AP style, to match Django

            var the_date = new Date(date_str + 'T00:00:00'); // tacking on zero time seems to keep it from timezoning
            var fmt = months[the_date.getMonth()] + ' ' + the_date.getDate() + ', ' + the_date.getFullYear();
            return fmt;
        },

        'time': function (time_str) {
            var the_time = new Date('2000-01-01T' + time_str); // need to make up a date to get it to parse
            var hours = the_time.getHours();
            var mins = the_time.getMinutes();
            var pm = false;
            if (hours == 0) {
                hours = 12;
            } else if (hours >= 12) {
                pm = true;
                if (hours > 12) {
                    hours -= 12;
                }
            }
            var fmt = hours;
            if (mins > 0) {
                fmt += ':' + (mins < 10 ? '0' + mins : mins);
            }
            fmt += ' ' + (pm ? 'p.m.' : 'a.m.'); // match Django format
            return fmt;
        },

        'textarea': function (str) {
            return str.replace(/\n/g, '<br/>');
        },

        '_': function(type) {
            return function (str) {
                return str;
            };
        }
    };

    var to_input = {
        'textarea': function(id, value) {
            var lines = unescape(value).split('\n');
            var max_line_len = lines.map(function(line) { return line.length; }).reduce(function(a, b) { return Math.max(a, b); });
            return '<textarea id="edit-' + id + '" rows=' + (lines.length + 1) + ' cols="' + (max_line_len + 5) + '">' + unescape(value) + '</textarea>';
        },

        '_': function(type) {
            return function(id, value) {
                return '<input id="edit-' + id + '" type="' + type + '" size=' + value.length + ' value="' + value + '"/>';
            };
        }
    };

    function lookup(arr, key) {
        if (key in arr) {
            return arr[key];
        } else {
            return arr['_'](key);
        }
    }

    function on_click(id, elem) {
        // if they clicked to select, don't do this
        if (window.getSelection().toString().length > 0) { return; }

        var data = $(elem).data();

        $(elem).replaceWith(lookup(to_input, data.type)(id, data.value));

        data.before_edit = data.value;
        $('#edit-' + id).data(data);
        $('#edit-' + id).blur(function() { on_blur(id, this) });
        $('#edit-' + id).focus();
    }

    function on_blur(id, elem) {
        // don't let an empty text box disappear
        if (elem.value.length == 0) {
            return false;
        }

        if ($(elem).data('before_edit') != elem.value) {
            $('#update-' + id)[0].value = escape(elem.value);

            $('#update-form').show();
        }

        var data = $(elem).data();
        var fmt = lookup(to_html, data.type)(elem.value);

        data.value = elem.value;
        $(elem).replaceWith('<span id="' + id + '" class="edit">' + fmt + '</span>');

        $('#' + id).data(data);
        make_editable('#' + id);
    }

    function make_editable(elem, first_time) {
        // add dotted underline
        $(elem).addClass('editable');

        // add tooltip
        if (input_support.indexOf($(elem).data('type')) != -1) {
            $(elem).attr('title', 'Click to edit');
            $(elem).click(function() { on_click(this.id, this); });
        } else {
            $(elem).attr('title', 'Can\'t edit ' + $(elem).data('type') + 's in this browser (try Chrome or Firefox)');
        }

        if (first_time) {
            // remember original value
            $(elem).data('original', $(elem).data('value'));

            // add invisible form field
            // turn off autocomplete so if you refresh the page the browser doesn't keep the values
            $('#update-form').append('<input type="text" name="' + elem.id + '" id="update-' + elem.id + '" class="hidden" autocomplete=off/>');
            $('#update-' + elem.id).attr('value', escape($(elem).data('value')));
        }
    }

    $('#edit-nav').click(function() {
        $('.edit').each(function(idx, elem) { make_editable(elem, true); });
        $(this).hide();
        $('#update-nav').show();
    });

    $('#update-form [value="update"]').click(function() {
        if ($('#registrants').length) {
            return confirm('Warning! Editing a meeting will send emails to each registrant. Proceed?');
        }
    });

    $('#reset-nav').click(function() {
        $('.edit').each(function(idx, elem) {
            // remove click handler
            $(elem).off('click');

            // remove invisible form field
            $('#update-' + elem.id).remove();

            // remove tooltip
            $(elem).removeAttr('title');

            // remove dotted underline
            $(elem).removeClass('editable');

            // restore original value
            var data = $(elem).data();
            var original = data.original;
            if (data.type in to_html) {
                elem.innerHTML = to_html[data.type](original);
            } else {
                elem.innerHTML = original;
            }
            $(elem).data('value', original);
        });

        $('#update-form').hide();
        $('#update-nav').hide();
        $('#edit-nav').show();
    });
}

